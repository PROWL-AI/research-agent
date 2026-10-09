"""Regression tests for audit batch B: render sanitization, citation-fidelity
honesty, writer lint guards, and chart validation."""

import logging
from pathlib import Path

import pytest

from research_agent.agent.citations import verify_citations
from research_agent.agent.writer import lint_report, write_and_repair
from research_agent.charts import _to_float, substitute_charts
from research_agent.evidence.ledger import Ledger
from research_agent.report.render import render_report_html

from conftest import FakeLLM


def _ledger(tmp_path: Path) -> Ledger:
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.add(
        claim="a.com traffic is 150,000",
        subject="a.com monthly organic traffic",
        value=150000,
        unit="visits/month",
        source_tool="spyfu_get_domain_stats",
    )
    ledger.add(
        claim="b.com channel has 430K subscribers",
        subject="b.com channel subscribers",
        value=430000,
        source_tool="youtube_search",
    )
    return ledger


class TestLinkSchemeSanitization:
    # B1: _escape_raw_html neutralises tags, but markdown links survive —
    # [x](javascript:…) becomes <a href="javascript:…">. Scraped content can
    # plant such a link (indirect prompt injection).

    def test_javascript_href_neutralised(self, tmp_path):
        html = render_report_html(
            "See [the data](javascript:alert(1)) for details.",
            _ledger(tmp_path), runbook="t", brief={}, stats={},
        )
        assert "javascript:" not in html
        assert 'href="#"' in html

    def test_blocked_schemes_and_case_variants(self, tmp_path):
        report = "\n\n".join(
            [
                "[a](JavaScript:alert(1))",
                "[b](data:text/html;base64,PHNjcmlwdD4=)",
                "[c](vbscript:msgbox(1))",
                "[d](file:///etc/passwd)",
            ]
        )
        html = render_report_html(
            report, _ledger(tmp_path), runbook="t", brief={}, stats={},
        )
        for scheme in ("javascript:", "data:", "vbscript:", "file:"):
            assert scheme not in html.lower()
        assert html.count('href="#"') == 4

    def test_safe_schemes_pass_through(self, tmp_path):
        html = render_report_html(
            "[site](https://example.com/?a=1) and [mail](mailto:a@b.c)",
            _ledger(tmp_path), runbook="t", brief={}, stats={},
        )
        assert 'href="https://example.com/?a=1"' in html
        assert 'href="mailto:a@b.c"' in html


class TestFidelityBudgetHonesty:
    # B2: sentences dropped by the 40-sentence budget must count as unchecked.

    async def test_budget_dropped_refs_count_as_unchecked(self, tmp_path, fake_llm: FakeLLM):
        ledger = _ledger(tmp_path)
        report = "\n\n".join(
            f"Finding {i}: a.com gets 150,00{i % 10} monthly visitors [C1]."
            for i in range(41)
        )
        fake_llm.fidelity_payload = {
            "verdicts": [
                {"s": s, "ref": "C1", "verdict": "supported"} for s in range(1, 11)
            ]
        }
        result = await verify_citations(fake_llm, report, ledger)
        assert result.checked == 40
        assert result.supported == 40
        assert result.unchecked == 1
        assert result.unverified == 0

    async def test_under_budget_nothing_dropped(self, tmp_path, fake_llm: FakeLLM):
        ledger = _ledger(tmp_path)
        report = "a.com gets 150,000 monthly visitors [C1]."
        fake_llm.fidelity_payload = {
            "verdicts": [{"s": 1, "ref": "C1", "verdict": "supported"}]
        }
        result = await verify_citations(fake_llm, report, ledger)
        assert result.checked == 1
        assert result.unchecked == 0


class TestRewriteKeepsUncheckedRefs:
    # B3: refs the LLM never ruled on must survive a rewrite triggered by a
    # sibling bad ref; only stats mark them unchecked.

    async def test_unchecked_ref_survives_sibling_rewrite(self, tmp_path, fake_llm: FakeLLM):
        ledger = _ledger(tmp_path)
        report = "a.com gets 150,000 monthly visitors [C1] and 430K subscribers [C2]."
        fake_llm.fidelity_payload = {
            "verdicts": [{"s": 1, "ref": "C2", "verdict": "unsupported"}]
        }
        result = await verify_citations(fake_llm, report, ledger)

        assert result.checked == 1
        assert result.supported == 0
        assert result.unverified == 1
        assert result.unchecked == 1
        assert "[C1]" in result.report_md
        assert "[C2]" not in result.report_md
        assert "[UNVERIFIED]" in result.report_md

    async def test_all_bad_still_replaces_sentence(self, tmp_path, fake_llm: FakeLLM):
        ledger = _ledger(tmp_path)
        report = "a.com has 430K subscribers [C2]."
        fake_llm.fidelity_payload = {
            "verdicts": [{"s": 1, "ref": "C2", "verdict": "subject-mismatch"}]
        }
        result = await verify_citations(fake_llm, report, ledger)
        assert "[UNVERIFIED: a.com has 430K subscribers.]" in result.report_md


class TestBareIdExemptionScope:
    # B5: a known bare C<n> exempts numbers only in conflict-register rows.

    def test_bare_id_in_plain_prose_does_not_cover_figures(self, tmp_path):
        ledger = _ledger(tmp_path)
        report = "As C1 shows, the market grew to 500,000 users last year."
        result = lint_report(report, ledger)
        assert any(i.kind == "uncited_number" for i in result.issues)

    def test_conflict_register_row_still_exempt(self, tmp_path):
        # Commit 0c29f63: the register writes refs unbracketed.
        ledger = _ledger(tmp_path)
        report = '- C1 vs C2: "Some Video — 2026" views (365,608 vs 365,614; timing)'
        result = lint_report(report, ledger)
        assert result.ok, result.issues

    def test_vs_pairing_row_still_exempt(self, tmp_path):
        ledger = _ledger(tmp_path)
        report = "Views diverge for C1 vs C2: 365,608 against 365,614."
        result = lint_report(report, ledger)
        assert result.ok, result.issues


class TestCollapsedRepair:
    # B6: an empty/gutted repair lints trivially clean — never ship it.

    async def test_empty_repair_keeps_previous_draft(
        self, tmp_path, fake_llm: FakeLLM, mini_runbooks_dir, monkeypatch
    ):
        from research_agent.runbook import get_runbook

        monkeypatch.setattr("research_agent.runbook.RUNBOOKS_DIR", mini_runbooks_dir)
        ledger = _ledger(tmp_path)
        draft = "Figures: 100,000 monthly visitors."
        fake_llm.text_queue = [draft, ""]
        outcome = await write_and_repair(
            fake_llm, get_runbook("mini-teardown"), ledger, {"competitors": ["a.com"]}
        )
        assert outcome.report_md == draft
        assert outcome.lint_before == 1
        assert outcome.lint_after == 1

    async def test_whitespace_repair_keeps_previous_draft(
        self, tmp_path, fake_llm: FakeLLM, mini_runbooks_dir, monkeypatch
    ):
        from research_agent.runbook import get_runbook

        monkeypatch.setattr("research_agent.runbook.RUNBOOKS_DIR", mini_runbooks_dir)
        ledger = _ledger(tmp_path)
        draft = "Figures: 100,000 monthly visitors."
        fake_llm.text_queue = [draft, "   \n  "]
        outcome = await write_and_repair(
            fake_llm, get_runbook("mini-teardown"), ledger, {"competitors": ["a.com"]}
        )
        assert outcome.report_md == draft
        assert outcome.lint_after == 1


class TestUnverifiedLabelNotACitation:
    # B7: a bare C<n> quoted inside an [UNVERIFIED: ...] label is a tombstone,
    # not a citation — no phantom missing_ref.

    def test_unverified_label_with_bare_ids_is_clean(self, tmp_path):
        ledger = _ledger(tmp_path)
        report = "[UNVERIFIED: C99 vs C98 views diverged]"
        result = lint_report(report, ledger)
        assert result.ok, result.issues

    def test_unknown_ref_outside_label_still_flagged(self, tmp_path):
        ledger = _ledger(tmp_path)
        report = "Traffic hit 150,000 visitors [C99]."
        result = lint_report(report, ledger)
        assert "C99" in result.missing_refs


class TestSuffixedLedgerValues:
    # B4: _to_float must parse the forms _NUMBER_RE lets into prose.

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("113K", 113000.0),
            ("4.2M", 4200000.0),
            ("$4.2M", 4200000.0),
            ("€2B", 2e9),
            ("£1,500", 1500.0),
            ("42 000", 42000.0),
            ("12%", 12.0),
            ("3.3M", 3300000.0),
            ("-5K", -5000.0),
            ("42000", 42000.0),
        ],
    )
    def test_to_float_parses_suffixed_forms(self, raw, expected):
        assert _to_float(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", ["n/a", "many", "1.2.3", ""])
    def test_to_float_rejects_non_numeric(self, raw):
        assert _to_float(raw) is None

    def test_chart_accepts_suffixed_ledger_values(self, tmp_path):
        ledger = Ledger(tmp_path / "ledger.json")
        ledger.add(claim="video views are 113K", subject="video views",
                   value="113K", unit="views", source_tool="t")
        ledger.add(claim="followers are 3.3M", subject="channel followers",
                   value="3.3M", unit="followers", source_tool="t")
        md = ('```chart {"type": "bar", "title": "reach", '
              '"labels": ["video views", "channel followers"], '
              '"values": [113000, 3300000], "claim_refs": ["C1", "C2"]}\n```')
        out = substitute_charts(md, ledger)
        assert "<svg" in out
        assert "```chart" not in out


class TestChartUnitAndLabelChecks:
    # B8: mixed unambiguous units reject; unmatched labels warn but render.

    def test_mixed_percent_and_currency_rejected(self, tmp_path):
        ledger = Ledger(tmp_path / "ledger.json")
        ledger.add(claim="conversion is 3.4%", subject="conversion rate",
                   value="3.4%", unit="%", source_tool="t")
        ledger.add(claim="revenue is $4.2M", subject="revenue",
                   value="$4.2M", unit="USD", source_tool="t")
        md = ('```chart {"type": "bar", "title": "mix", '
              '"labels": ["conversion rate", "revenue"], '
              '"values": [3.4, 4200000], "claim_refs": ["C1", "C2"]}\n```')
        out = substitute_charts(md, ledger)
        assert "[chart rejected: values mix incompatible units" in out
        assert "<svg" not in out

    def test_same_kind_units_render(self, tmp_path):
        ledger = Ledger(tmp_path / "ledger.json")
        ledger.add(claim="a.com traffic", subject="a.com traffic",
                   value="42K", unit="visits/month", source_tool="t")
        ledger.add(claim="b.com traffic", subject="b.com traffic",
                   value="118K", unit="visits/month", source_tool="t")
        md = ('```chart {"type": "bar", "title": "traffic", '
              '"labels": ["a.com", "b.com"], '
              '"values": [42000, 118000], "claim_refs": ["C1", "C2"]}\n```')
        out = substitute_charts(md, ledger)
        assert "<svg" in out

    def test_unmatched_labels_warn_but_render(self, tmp_path, caplog):
        ledger = Ledger(tmp_path / "ledger.json")
        ledger.add(claim="a.com traffic is 100", subject="a.com traffic",
                   value=100, unit="visits", source_tool="t")
        ledger.add(claim="b.com traffic is 200", subject="b.com traffic",
                   value=200, unit="visits", source_tool="t")
        md = ('```chart {"type": "bar", "title": "traffic", '
              '"labels": ["zephyr", "quasar"], '
              '"values": [100, 200], "claim_refs": ["C1", "C2"]}\n```')
        with caplog.at_level(logging.WARNING, logger="research_agent.charts"):
            out = substitute_charts(md, ledger)
        assert "<svg" in out
        assert any("no label matches" in r.message for r in caplog.records)
