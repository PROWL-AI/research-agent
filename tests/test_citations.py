from pathlib import Path

import pytest

from research_agent.agent.citations import verify_citations
from research_agent.agent.orchestrator import Orchestrator
from research_agent.agent.writer import lint_report
from research_agent.evidence.ledger import Ledger

from conftest import FakeLLM, FakeProwl


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


async def test_subject_mismatch_marked_unverified_good_kept(tmp_path, fake_llm: FakeLLM):
    ledger = _ledger(tmp_path)
    report = (
        "a.com gets 150,000 monthly visitors [C1].\n\n"
        "a.com has 430K subscribers [C2]."
    )
    fake_llm.fidelity_payload = {
        "verdicts": [
            {"s": 1, "ref": "C1", "verdict": "supported"},
            {"s": 2, "ref": "C2", "verdict": "subject-mismatch"},
        ]
    }
    result = await verify_citations(fake_llm, report, ledger)

    assert result.checked == 2
    assert result.supported == 1
    assert result.unverified == 1
    assert "[C1]" in result.report_md
    assert "[C2]" not in result.report_md
    assert "[UNVERIFIED: a.com has 430K subscribers.]" in result.report_md


async def test_mixed_sentence_keeps_good_ref_marks_bad(tmp_path, fake_llm: FakeLLM):
    ledger = _ledger(tmp_path)
    report = "a.com gets 150,000 monthly visitors [C1] and 430K subscribers [C2]."
    fake_llm.fidelity_payload = {
        "verdicts": [
            {"s": 1, "ref": "C1", "verdict": "supported"},
            {"s": 1, "ref": "C2", "verdict": "unsupported"},
        ]
    }
    result = await verify_citations(fake_llm, report, ledger)

    assert result.supported == 1
    assert result.unverified == 1
    assert "[C1]" in result.report_md
    assert "[C2]" not in result.report_md
    assert "[UNVERIFIED]" in result.report_md


async def test_missing_verdict_counts_as_unchecked_not_supported(tmp_path, fake_llm: FakeLLM):
    # A ref the LLM never ruled on is unchecked — silence must not report as
    # a clean pass (the old default-supported hid full batch failures).
    ledger = _ledger(tmp_path)
    report = "a.com gets 150,000 monthly visitors [C1]."
    result = await verify_citations(fake_llm, report, ledger)
    assert result.checked == 0
    assert result.supported == 0
    assert result.unchecked == 1
    assert result.report_md == report


def test_lint_accepts_unverified_marker(tmp_path):
    ledger = _ledger(tmp_path)
    report = "a.com has 430K subscribers [UNVERIFIED: a.com has 430K subscribers.]"
    assert lint_report(report, ledger).ok


async def test_fidelity_stats_in_run_result(
    patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
):
    fake_llm.plan_payload = {
        "plan": [
            {"step": "baseline", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "a.com"}}
        ]
    }
    fake_llm.claims_payload = {
        "claims": [
            {"claim": "a.com traffic is 150,000", "subject": "a.com monthly organic traffic",
             "value": 150000, "unit": "visits/month"},
            {"claim": "b.com channel has 430K subscribers", "subject": "b.com channel subscribers",
             "value": 430000},
        ]
    }
    fake_llm.report_text = (
        "a.com gets 150,000 monthly visitors [C1].\n\n"
        "a.com has 430K subscribers [C2]."
    )
    fake_llm.fidelity_payload = {
        "verdicts": [
            {"s": 1, "ref": "C1", "verdict": "supported"},
            {"s": 2, "ref": "C2", "verdict": "subject-mismatch"},
        ]
    }
    orchestrator = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")
    result = await orchestrator.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r-fid")

    assert result.stats["citation_fidelity"] == {
        "checked": 2, "supported": 1, "unverified": 1, "unchecked": 0,
    }
    report = Path(result.report_path).read_text()
    assert "[UNVERIFIED:" in report
    assert "[C1]" in report
