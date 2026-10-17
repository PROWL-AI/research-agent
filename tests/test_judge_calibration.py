"""Wave 6 (W6-T1): the judge rejects planted defects by code, and its own LLM spend is metered.

KA-G02 asks that the judge fail planted-bad output before it is trusted on real runs. Here the
model is made maximally lenient (0.95 on every dimension): every planted fixture must still fail,
because each defect is caught by a code check — and the honest fixtures must still pass."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals"))

import calibrate  # noqa: E402
import judge  # noqa: E402

from research_agent.evidence.ledger import Ledger  # noqa: E402
from research_agent.evidence.store import Checkpoint  # noqa: E402
from research_agent.llm import LLMClient  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "evals" / "fixtures" / "planted"


class LenientJudge:
    """A judge model that would pass anything: 0.95 on every dimension."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages, tier="cheap", json_mode=False, **kwargs):
        self.calls += 1
        return json.dumps({"scores": {d: 0.95 for d in judge.DIMENSIONS},
                           "reasons": {d: "looks fine" for d in judge.DIMENSIONS}})


def _fixtures():
    return sorted(FIXTURES.glob("*.json"))


def test_the_fixture_set_covers_every_defect_kind_and_an_honest_report():
    labels = [json.loads(p.read_text()) for p in _fixtures()]
    planted = {kind for f in labels if f["label"] == "fail" for kind in f["defects"]}
    assert planted >= {"missing_ref", "quote_not_in_ledger", "value_mismatch", "conflict_hidden",
                       "partial_undisclosed"}
    assert any(f["label"] == "pass" for f in labels)
    assert all(f["label"] in {"pass", "fail"} for f in labels)


@pytest.mark.parametrize("path", _fixtures(), ids=lambda p: p.stem)
async def test_a_lenient_judge_still_fails_every_planted_defect(tmp_path, path):
    fixture = json.loads(path.read_text())
    row = await calibrate.judge_fixture(fixture, LenientJudge(), tmp_path)
    assert row["verdict"] == ("PASS" if fixture["label"] == "pass" else "FAIL"), row
    assert sorted({d["kind"] for d in row["defects"]}) == sorted(fixture["defects"]), row


async def test_the_harness_reports_agreement_and_fails_when_a_planted_fixture_passes(tmp_path):
    rows = await calibrate.calibrate(LenientJudge(), FIXTURES, tmp_path)
    summary = calibrate.summarize(rows)
    assert summary["agreement"] == 1.0 and summary["missed"] == [] and summary["false_alarms"] == []
    rows[0]["verdict"] = "PASS" if rows[0]["label"] == "fail" else "FAIL"
    assert calibrate.summarize(rows)["agreement"] < 1.0


# ── the code checks, one by one ────────────────────────────────────────────────

def _ledger(tmp_path, *claims):
    ledger = Ledger(tmp_path / "ledger.json")
    for claim in claims:
        ledger.add(**claim)
    return ledger


TRAFFIC = dict(claim="example.com traffic is 150,000 visits/month", subject="example.com traffic",
               value=150000, unit="visits/month", source_tool="spyfu_get_domain_stats",
               quote="monthly visits 150000")


def _kinds(report, ledger, partial=False):
    checkpoint = Checkpoint(run_id="r", runbook="calibration-teardown")
    checkpoint.partial = partial
    return [d["kind"] for d in judge.code_defects(report, ledger, checkpoint)]


@pytest.mark.parametrize("sentence,expected", [
    ("Traffic is 150,000 visits a month [C1].", []),
    ("Traffic is 150k visits a month [C1].", []),
    ("Traffic is about 0.15M visits [C1] (ASSUMED, ±40%).", []),
    ("Traffic is 420,000 visits a month [C1].", ["value_mismatch"]),
    ("Traffic reached 150,000 in 2026-10-07 data [C1].", []),
    ("Traffic is high [C1].", []),  # no number: nothing to compare
    ("Its ads lean on Fortune 500 credibility [C1].", []),  # a number in a name is not a figure
    ("Traffic is 0.15 million visits [C1].", []),
    ("Traffic is 1.5 million visits [C1].", ["value_mismatch"]),
])
def test_value_mismatch(tmp_path, sentence, expected):
    assert _kinds("# Report\n\n" + sentence + "\n", _ledger(tmp_path, TRAFFIC)) == expected


def test_an_invented_quote_is_a_defect_and_a_real_one_is_not(tmp_path):
    ledger = _ledger(tmp_path, TRAFFIC)
    assert _kinds('# R\n\nThe dashboard says "monthly visits 150000" [C1].\n', ledger) == []
    # a source title beside the backed quotation, and a headline in the claim's own words
    assert _kinds('# R\n\n"Rival Traffic Report" (Blog) — "monthly visits 150000" [C1].\n', ledger) == []
    assert _kinds('# R\n\n"Example.com Traffic Is 150,000 Visits/Month" (Blog) [C1].\n', ledger) == []
    assert _kinds('# R\n\nThe CEO said "we doubled traffic overnight" [C1].\n', ledger) == ["quote_not_in_ledger"]


def test_a_conflict_must_be_shown_as_one(tmp_path):
    ledger = _ledger(tmp_path,
                     dict(claim="paid keywords 300", subject="example.com paid keywords", value=300,
                          source_tool="spyfu_get_domain_stats"),
                     dict(claim="paid keywords 900", subject="example.com paid keywords", value=900,
                          source_tool="dataforseo_bl_summary"))
    assert _kinds("# R\n\nPaid keywords: 300 [C1] vs 900 [C2] [CONFLICT].\n", ledger) == []
    assert _kinds("# R\n\nThe rival bids on 300 paid keywords [C1].\n", ledger) == ["conflict_hidden"]


def test_a_partial_run_must_say_so_first(tmp_path):
    ledger = _ledger(tmp_path, TRAFFIC)
    assert _kinds("# Teardown — PARTIAL: evidence only\n\nTraffic 150,000 [C1].\n", ledger, partial=True) == []
    assert _kinds("# Teardown\n\n**PARTIAL RUN NOTICE**: two steps failed.\n\n## Summary\n\nTraffic 150,000 [C1].\n",
                  ledger, partial=True) == []  # a preamble before the first section discloses it too
    assert _kinds("# Teardown\n\nTraffic 150,000 [C1].\n", ledger, partial=True) == ["partial_undisclosed"]
    assert _kinds("# Teardown\n\n## Summary\n\nThe run was partial [C1].\n", ledger, partial=True) == ["partial_undisclosed"]


def test_a_citation_of_no_claim_is_a_defect(tmp_path):
    assert _kinds("# R\n\nTraffic 150,000 [C1]; churn is low [C7].\n", _ledger(tmp_path, TRAFFIC)) == ["missing_ref"]


async def test_a_defect_vetoes_a_high_score(tmp_path, monkeypatch):
    fixture = json.loads((FIXTURES / "value-mismatch.json").read_text())
    row = await calibrate.judge_fixture(fixture, LenientJudge(), tmp_path)
    assert row["total"] >= judge.DEFAULT_THRESHOLD and row["verdict"] == "FAIL"


# ── B-041: the judge's own spend ───────────────────────────────────────────────

def _billing_llm(cost: float, calls: list) -> LLMClient:
    def provider(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        content = json.dumps({"scores": {d: 0.9 for d in judge.DIMENSIONS}, "reasons": {}})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": cost}})

    llm = LLMClient("http://llm.invalid", "test-not-a-key", "cheap", "strong")
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    return llm


async def test_the_judge_spend_is_recorded_beside_the_run_not_in_it(tmp_path):
    fixture = json.loads((FIXTURES / "honest.json").read_text())
    run_dir = calibrate.build_run(fixture, tmp_path)
    before = (run_dir / "checkpoint.json").read_bytes()
    calls: list = []
    async with _billing_llm(0.012, calls) as llm:
        result = await judge.judge_run(run_dir, llm, max_usd=0.5, runbooks_dir=calibrate.RUNBOOKS)
        assert llm.meter is None  # the judge's meter is detached afterwards
    assert result.spend_usd == pytest.approx(0.012)
    ledger = json.loads((run_dir / "judge-ledger.json").read_text())
    attempt = ledger["sessions"][-1]["attempts"][0]
    assert attempt["kind"] == "llm" and attempt["step_id"] == "judge" and attempt["actual_usd"] == 0.012
    assert (run_dir / "checkpoint.json").read_bytes() == before


async def test_the_judge_refuses_to_spend_above_its_ceiling(tmp_path):
    fixture = json.loads((FIXTURES / "honest.json").read_text())
    run_dir = calibrate.build_run(fixture, tmp_path)
    calls: list = []
    async with _billing_llm(0.012, calls) as llm:
        with pytest.raises(judge.JudgeError, match="judge budget"):
            await judge.judge_run(run_dir, llm, max_usd=0.000001, runbooks_dir=calibrate.RUNBOOKS)
    assert calls == []  # refused before anything was sent


def test_the_cli_exit_codes_keep_a_judge_error_apart_from_a_fail():
    assert judge.EXIT_PASS == 0 and judge.EXIT_FAIL == 1 and judge.EXIT_ERROR == 2


@pytest.mark.parametrize("sentence,expected", [
    ("The rival is valued at $4B [C1].", []),
    ("The rival is valued at $4.0 billion [C1].", []),
    ("The rival is valued at $4 [C1].", ["value_mismatch"]),
])
def test_a_scale_right_after_the_number_is_read(tmp_path, sentence, expected):
    valuation = dict(claim="rival valuation USD 4,000,000,000", subject="rival valuation", value=4_000_000_000,
                     unit="USD", source_tool="spyfu_get_domain_stats")
    assert _kinds("# R\n\n" + sentence + "\n", _ledger(tmp_path, valuation)) == expected


async def test_completeness_and_source_quality_are_capped_by_code(tmp_path):
    fixture = json.loads((FIXTURES / "honest.json").read_text())
    fixture = dict(fixture, name="no-source-log",
                   report=fixture["report"].split("## Source log")[0])  # one of two required sections
    fixture["claims"] = [dict(c, source_tool="perplexity_responses") if c["value"] == 1200 else c
                         for c in fixture["claims"]]  # one claim from an LLM-answer tool
    run_dir = calibrate.build_run(fixture, tmp_path)
    result = await judge.judge_run(run_dir, LenientJudge(), runbooks_dir=calibrate.RUNBOOKS)
    assert result.scores["completeness"] == 0.5 and result.scores["source_quality"] == 0.5


# ── fix round: the writer's own conventions are not defects ────────────────────

PK = [dict(claim="paid keywords 300", subject="example.com paid keywords", value=300, source_tool="spyfu_get_domain_stats"),
      dict(claim="paid keywords 900", subject="example.com paid keywords", value=900, source_tool="dataforseo_bl_summary")]


@pytest.mark.parametrize("body", [
    "Paid keywords: 300 [C1] vs. 900 [C2] [CONFLICT].",                       # an abbreviation is no sentence end
    "### [CONFLICT] register\n\n- 300 paid keywords [C1]\n- 900 paid keywords [C2]",   # the runbooks' register
    "### Conflict register\n\n- 300 [C1]\n- 900 [C2]",
    "Two sources disagree [CONFLICT]:\n\n- 300 paid keywords [C1]\n- 900 paid keywords [C2]",  # register lead-in
    "## Source log\n\n- 300 paid keywords — spyfu [C1], retrieved 2026-10-07.",  # provenance rows
])
def test_the_conflict_conventions_the_runbooks_require_are_disclosure(tmp_path, body):
    assert _kinds("# R\n\n" + body + "\n", _ledger(tmp_path, *PK)) == []


def test_a_conflict_hidden_behind_a_composite_unverified_block_is_still_seen(tmp_path):
    ledger = _ledger(tmp_path, TRAFFIC, *PK)
    assert _kinds("# R\n\nThe rival bids on 300 paid keywords [UNVERIFIED, C2].\n", ledger) == ["conflict_hidden"]


def test_a_quoted_search_phrase_is_not_a_quotation(tmp_path):
    ledger = _ledger(tmp_path, TRAFFIC)
    assert _kinds('# R\n\nCapture "how to use rival" search traffic, 150,000 visits [C1].\n', ledger) == []


def test_a_wrong_figure_beside_two_citations_is_still_a_mismatch(tmp_path):
    links = dict(claim="1,200 referring domains", subject="example.com referring domains", value=1200,
                 source_tool="dataforseo_bl_summary")
    ledger = _ledger(tmp_path, TRAFFIC, links)
    assert _kinds("# R\n\nexample.com draws 420,000 visitors [C1][C2].\n", ledger) == ["value_mismatch"]
    assert _kinds("# R\n\nexample.com draws 150,000 visitors and 1,200 domains [C1][C2].\n", ledger) == []


def test_the_judge_needs_no_prowl_key_and_a_model_failure_is_exit_2(tmp_path, monkeypatch, capsys):
    fixture = json.loads((FIXTURES / "honest.json").read_text())
    run_dir = calibrate.build_run(fixture, tmp_path)
    monkeypatch.setattr("research_agent.runbook.RUNBOOKS_DIR", calibrate.RUNBOOKS)
    monkeypatch.delenv("PROWL_API_KEY", raising=False)
    monkeypatch.setenv("RESEARCH_LLM_API_KEY", "test-not-a-key")
    monkeypatch.setenv("RESEARCH_LLM_BASE_URL", "http://127.0.0.1:9/v1")  # nothing listens

    async def no_sleep(_):
        return None

    monkeypatch.setattr("research_agent.llm.asyncio.sleep", no_sleep)
    assert judge.main(["--run", str(run_dir)]) == judge.EXIT_ERROR
    err = capsys.readouterr().err
    assert "judge model call failed" in err and "PROWL_API_KEY" not in err


def test_a_run_that_turns_partial_after_the_writer_says_so():
    from research_agent.agent.writer import disclose_partial, partial_disclosed

    report = "# Teardown\n\n## Summary\n\nTraffic 150,000 [C1].\n"
    disclosed = disclose_partial(report, "max_llm_usd=1.0 reached")
    assert partial_disclosed(disclosed) and disclosed.startswith("# Teardown\n\n**PARTIAL RUN:** max_llm_usd=1.0")
    assert disclose_partial(disclosed, "x") == disclosed  # idempotent
    assert disclosed.endswith("[C1].\n")


@pytest.mark.parametrize("sentence,expected", [
    ("Average interest 150000 [C1] vs. last year's 60% rise.", []),  # a bare number carries the value
    ("Engagement is 3.4% (derived: visits [C1] over followers).", []),  # the writer's derived rule
    ("Traffic is 150,000 visits vs. 420,000 a year ago [C1].", []),  # "vs." does not end the sentence
    ("Traffic fell 40% to a new low [C1].", ["value_mismatch"]),
])
def test_bare_numbers_carry_values_and_derived_figures_are_exempt(tmp_path, sentence, expected):
    assert _kinds("# R\n\n" + sentence + "\n", _ledger(tmp_path, TRAFFIC)) == expected


# ── second fix round: what a substring used to let through ────────────────────

@pytest.mark.parametrize("body", [
    "## Channel conflict and pricing\n\nThe rival bids on 300 paid keywords [C1].",
    "Two channels are conflicting here. The rival bids on 300 paid keywords [C1].",
    "## Source log and key findings\n\n- The rival bids on 300 paid keywords [C1].",
])
def test_the_word_conflict_somewhere_nearby_is_not_disclosure(tmp_path, body):
    assert _kinds("# R\n\n" + body + "\n", _ledger(tmp_path, *PK)) == ["conflict_hidden"]


def test_a_conflict_register_written_as_a_table_is_disclosure(tmp_path):
    body = "Sources disagree [CONFLICT]:\n\n| Claim | Value |\n|---|---|\n| paid keywords [C1] | 300 |\n| paid keywords [C2] | 900 |"
    assert _kinds("# R\n\n" + body + "\n", _ledger(tmp_path, *PK)) == []


@pytest.mark.parametrize("sentence,expected", [
    ("Traffic is 420,000 visits, derived from the panel [C1].", ["value_mismatch"]),  # "derived from" is no mark
    ("Traffic is $150K a month [C1].", []),  # the scale is read: 150K is the claim's 150,000
])
def test_derived_from_is_not_the_derived_mark(tmp_path, sentence, expected):
    assert _kinds("# R\n\n" + sentence + "\n", _ledger(tmp_path, TRAFFIC)) == expected


def test_a_number_inside_a_scaled_figure_carries_no_value(tmp_path):
    staff = dict(claim="the rival employs 12 people", subject="rival staff", value=12, unit="employees",
                 source_tool="spyfu_get_domain_stats")
    assert _kinds("# R\n\nThe rival raised $12M [C1].\n", _ledger(tmp_path, staff)) == ["value_mismatch"]
    assert _kinds("# R\n\nThe rival employs 12 people [C1].\n", _ledger(tmp_path, staff)) == []


def test_a_non_numeric_co_citation_does_not_silence_the_value_check(tmp_path):
    note = dict(claim="the rival focuses on enterprise buyers", subject="rival focus", source_tool="spyfu_get_domain_stats")
    ledger = _ledger(tmp_path, TRAFFIC, note)
    assert _kinds("# R\n\nexample.com draws 420,000 visitors [C1, C2].\n", ledger) == ["value_mismatch"]
    assert _kinds("# R\n\nexample.com draws 150,000 visitors [C1, C2].\n", ledger) == []


def test_impartial_is_not_a_partial_disclosure():
    from research_agent.agent.writer import partial_disclosed

    assert not partial_disclosed("# Impartial review of the rival\n\n## Summary\n")
    assert partial_disclosed("# Teardown — PARTIAL: evidence only\n")


async def test_a_judge_ledger_that_cannot_be_written_is_a_judge_error(tmp_path, monkeypatch):
    fixture = json.loads((FIXTURES / "honest.json").read_text())
    run_dir = calibrate.build_run(fixture, tmp_path)

    def broken(self):
        raise OSError("read-only file system")

    monkeypatch.setattr(judge._JudgeLedger, "save", broken)
    calls: list = []
    async with _billing_llm(0.01, calls) as llm:
        with pytest.raises(judge.JudgeError, match="judge ledger could not be written"):
            await judge.judge_run(run_dir, llm, max_usd=0.5, runbooks_dir=calibrate.RUNBOOKS)


def test_a_non_numeric_claim_carries_the_figures_in_its_text(tmp_path):
    links = dict(claim="the rival has 1,200 referring domains", subject="rival links", source_tool="dataforseo_bl_summary")
    ledger = _ledger(tmp_path, links)
    assert _kinds("# R\n\nThe rival has 1,200 referring domains [C1].\n", ledger) == []
    assert _kinds("# R\n\nThe rival has 4,000 referring domains [C1].\n", ledger) == ["value_mismatch"]
