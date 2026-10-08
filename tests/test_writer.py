from research_agent.agent.writer import lint_report
from research_agent.evidence.ledger import Ledger

from conftest import load_fixture


def _ledger_with(tmp_path, *subjects):
    ledger = Ledger(tmp_path / "ledger.json")
    for subject in subjects:
        ledger.add(claim=f"fact about {subject}", subject=subject, value=1, source_tool="t")
    return ledger


def test_lint_flags_uncited_estimate(tmp_path):
    fixture = load_fixture("t6_hallucinated_precision.json")
    ledger = _ledger_with(tmp_path, "x")
    result = lint_report(fixture["report_excerpt"], ledger)
    assert not result.ok
    assert "150,000" in result.uncited_numbers


def test_lint_passes_cited_number(tmp_path):
    ledger = _ledger_with(tmp_path, "x")
    report = "The rival attracts an estimated 150,000 monthly visitors [C1] (ASSUMED, ±40%)."
    result = lint_report(report, ledger)
    assert result.ok, result.issues


def test_lint_flags_missing_ledger_ref(tmp_path):
    ledger = _ledger_with(tmp_path, "x")
    report = "Traffic is 150,000 monthly visitors [C99]."
    result = lint_report(report, ledger)
    assert not result.ok
    assert "C99" in result.missing_refs
    assert not result.uncited_numbers


def test_lint_ignores_prose_without_metrics(tmp_path):
    ledger = _ledger_with(tmp_path, "x")
    result = lint_report("The rival positions itself as the fastest option on the market.", ledger)
    assert result.ok


def test_writer_prompt_states_hard_rule_with_example():
    from research_agent.agent.writer import WRITER_SYSTEM_TEMPLATE

    assert "IMMEDIATELY after the figure" in WRITER_SYSTEM_TEMPLATE
    assert "[UNVERIFIED]" in WRITER_SYSTEM_TEMPLATE
    assert "WRONG" in WRITER_SYSTEM_TEMPLATE
    assert "RIGHT" in WRITER_SYSTEM_TEMPLATE
    assert "[CONFLICT]" in WRITER_SYSTEM_TEMPLATE
    assert "Source Log" in WRITER_SYSTEM_TEMPLATE


def test_repair_prompt_forbids_invented_citations():
    from research_agent.agent.writer import REPAIR_SYSTEM_TEMPLATE

    assert "NEVER invent" in REPAIR_SYSTEM_TEMPLATE or "do NOT invent" in REPAIR_SYSTEM_TEMPLATE
    assert "subject" in REPAIR_SYSTEM_TEMPLATE


def _outcome_ledger(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.add(claim="views are 113K", subject="video views", value=113000,
               source_tool="youtube_search")
    ledger.add(claim="followers are 3.3M", subject="channel followers", value=3300000,
               source_tool="youtube_search")
    return ledger


def _strong_nonjson_calls(fake_llm):
    return [c for c in fake_llm.calls if c["tier"] == "strong" and not c["json_mode"]]


async def test_multi_pass_repair_reduces_then_cleans(tmp_path, fake_llm, mini_runbooks_dir, monkeypatch):
    from research_agent.agent.writer import write_and_repair
    from research_agent.runbook import get_runbook

    monkeypatch.setattr("research_agent.runbook.RUNBOOKS_DIR", mini_runbooks_dir)
    ledger = _outcome_ledger(tmp_path)
    fake_llm.text_queue = [
        "Numbers: 100,000 monthly visitors, 200,000 monthly visitors, 50%, $10,000, 25,000 keywords.",
        "Remaining: 200,000 monthly visitors and 50%.",
        "All figures now cited [C1].",
    ]
    outcome = await write_and_repair(
        fake_llm, get_runbook("mini-teardown"), ledger, {"competitors": ["a.com"]}
    )
    assert outcome.lint_before == 5
    assert outcome.lint_after == 0
    assert outcome.repair_passes == 2
    assert outcome.revised is True
    assert len(_strong_nonjson_calls(fake_llm)) == 3


async def test_repair_stops_when_the_issue_SET_repeats(
    tmp_path, fake_llm, mini_runbooks_dir, monkeypatch
):
    from research_agent.agent.writer import write_and_repair
    from research_agent.runbook import get_runbook

    monkeypatch.setattr("research_agent.runbook.RUNBOOKS_DIR", mini_runbooks_dir)
    ledger = _outcome_ledger(tmp_path)
    fake_llm.text_queue = [
        "Figures: 100,000 monthly visitors, 200,000 monthly visitors, 50%.",
        "Figures: 100,000 monthly visitors, 200,000 monthly visitors, 50%.",
        "this third text must never be used",
    ]
    outcome = await write_and_repair(
        fake_llm, get_runbook("mini-teardown"), ledger, {"competitors": ["a.com"]}
    )
    assert outcome.lint_before == 3
    assert outcome.lint_after == 3
    assert outcome.repair_passes == 1
    assert len(_strong_nonjson_calls(fake_llm)) == 2


async def test_repair_continues_when_the_set_changes_at_equal_count(
    tmp_path, fake_llm, mini_runbooks_dir, monkeypatch
):
    # The bug: stopping on "8 -> 8 issues" when the repair fixed 8 old ones
    # and introduced 8 new ones. A DIFFERENT (kind, text) set at equal count
    # is progress — the loop must continue.
    from research_agent.agent.writer import write_and_repair
    from research_agent.runbook import get_runbook

    monkeypatch.setattr("research_agent.runbook.RUNBOOKS_DIR", mini_runbooks_dir)
    ledger = _outcome_ledger(tmp_path)
    fake_llm.text_queue = [
        "Figures: 100,000 monthly visitors, 200,000 monthly visitors, 50%.",
        "Figures: 300,000 monthly visitors, 400,000 monthly visitors, 60%.",
        "All figures now derived from [C1].",
    ]
    outcome = await write_and_repair(
        fake_llm, get_runbook("mini-teardown"), ledger, {"competitors": ["a.com"]}
    )
    assert outcome.lint_before == 3
    assert outcome.lint_after == 0
    assert outcome.repair_passes == 2
    assert len(_strong_nonjson_calls(fake_llm)) == 3


def test_lint_accepts_assumption_marker(tmp_path):
    ledger = _outcome_ledger(tmp_path)
    report = "Aim for 5%+ CTR on the hero creative (target, assumption — not data)."
    result = lint_report(report, ledger)
    assert result.ok, result.issues


def test_lint_accepts_derived_with_input_refs(tmp_path):
    ledger = _outcome_ledger(tmp_path)
    report = "Engagement is 3.4% (derived: 113K views [C1] / 3.3M followers [C2])."
    result = lint_report(report, ledger)
    assert result.ok, result.issues


def test_lint_still_flags_bare_target_without_marker(tmp_path):
    ledger = _outcome_ledger(tmp_path)
    result = lint_report("Aim for 5% CTR on the hero creative.", ledger)
    assert not result.ok
    assert "5%" in result.uncited_numbers


def test_templates_carry_derived_and_assumption_rules():
    from research_agent.agent.writer import REPAIR_SYSTEM_TEMPLATE, WRITER_SYSTEM_TEMPLATE

    assert "derived" in WRITER_SYSTEM_TEMPLATE
    assert "(target, assumption — not data)" in WRITER_SYSTEM_TEMPLATE
    assert "EXACTLY ONE action" in REPAIR_SYSTEM_TEMPLATE
    assert "(target, assumption — not data)" in REPAIR_SYSTEM_TEMPLATE
    assert "Never leave a bare number" in REPAIR_SYSTEM_TEMPLATE


def test_lint_accepts_bare_ledger_ids_in_conflict_register(tmp_path):
    # The conflict register writes refs unbracketed ("C41 vs C126: ..."):
    # the reference is traceable, only the format differs from RULE 0.
    ledger = _outcome_ledger(tmp_path)
    first = next(iter([c for c in ledger.claims]), None)
    assert first is not None
    report = (
        f'- {first.id} vs C2: "Some Video — 2026" views '
        f'(365,608 vs 365,614; likely measurement timing difference)'
    )
    result = lint_report(report, ledger)
    assert result.ok, result.issues


def test_lint_unknown_bare_id_never_covers_a_figure(tmp_path):
    ledger = _outcome_ledger(tmp_path)
    report = "- C999 vs C998: views hit 365,608 and climbing"
    result = lint_report(report, ledger)
    assert any(i.kind == "uncited_number" for i in result.issues)
