import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals"))

import judge

from research_agent.evidence.ledger import Ledger
from research_agent.evidence.store import Checkpoint

from conftest import FakeLLM

GOOD_REPORT = """\
# Mini Teardown Report

## Executive summary

The rival attracts an estimated 150,000 monthly visitors [C1] (ASSUMED, ±40%).

## Source log

- 150,000 monthly visitors — spyfu_get_domain_stats [C1], retrieved 2026-10-07.
"""

BAD_REPORT = """\
# Mini Teardown Report

## Executive summary

Rival.io is the clear traffic leader in the space. It attracts an estimated
150,000 monthly visitors and converts them efficiently, which suggests a
strong organic engine behind the brand.
"""


def _make_run(tmp_path: Path, run_id: str, report_md: str) -> Path:
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "report.md").write_text(report_md, encoding="utf-8")
    ledger = Ledger(run_dir / "ledger.json")
    ledger.add(
        claim="a.com traffic is 150,000",
        subject="a.com traffic",
        value=150000,
        unit="visits/month",
        source_tool="spyfu_get_domain_stats",
    )
    ledger.save()
    checkpoint = Checkpoint(run_id=run_id, runbook="mini-teardown")
    checkpoint.counters["data_calls"] = 1
    (run_dir / "checkpoint.json").write_text(checkpoint.model_dump_json())
    return run_dir


def _scores(value: float, **overrides: float) -> dict:
    scores = {dim: value for dim in judge.DIMENSIONS}
    scores.update(overrides)
    return {"scores": scores, "reasons": {dim: "" for dim in judge.DIMENSIONS}}


@pytest.fixture
def patched_runbooks(monkeypatch, mini_runbooks_dir):
    monkeypatch.setattr("research_agent.runbook.RUNBOOKS_DIR", mini_runbooks_dir)
    return mini_runbooks_dir


async def test_good_report_passes(patched_runbooks, tmp_path):
    run_dir = _make_run(tmp_path, "j-good", GOOD_REPORT)
    llm = FakeLLM()
    llm.plan_payload = _scores(0.9)

    result = await judge.judge_run(run_dir, llm)

    assert result.passed is True
    assert result.total >= judge.DEFAULT_THRESHOLD
    assert result.scores["citation_accuracy"] == 0.9
    assert result.signals["sections"]["missing"] == []
    assert result.signals["lint"]["uncited_numbers"] == []


async def test_t6_style_uncited_report_fails(patched_runbooks, tmp_path):
    run_dir = _make_run(tmp_path, "j-bad", BAD_REPORT)
    llm = FakeLLM()
    llm.plan_payload = _scores(0.6, citation_accuracy=0.9)

    result = await judge.judge_run(run_dir, llm)

    assert result.passed is False
    assert result.total < judge.DEFAULT_THRESHOLD
    assert result.signals["lint"]["uncited_numbers"] == ["150,000"]
    assert result.scores["citation_accuracy"] == 0.5
    prompt = llm.calls[0]["messages"][1]["content"]
    assert "150,000" in prompt and "uncited_numbers" in prompt


async def test_threshold_override(patched_runbooks, tmp_path):
    run_dir = _make_run(tmp_path, "j-threshold", GOOD_REPORT)
    llm = FakeLLM()
    llm.plan_payload = _scores(0.9)

    result = await judge.judge_run(run_dir, llm, threshold=0.95)
    assert result.passed is False


def test_section_coverage_detects_missing():
    coverage = judge.section_coverage(
        GOOD_REPORT, ["Executive summary", "Source log", "Battlecard"]
    )
    assert coverage["covered"] == ["Executive summary", "Source log"]
    assert coverage["missing"] == ["Battlecard"]


def test_ledger_stats_flags_llm_derived(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.add(claim="a", subject="s1", value=1, source_tool="spyfu_get_domain_stats")
    ledger.add(claim="b", subject="s2", value=2, source_tool="perplexity_responses")
    stats = judge.ledger_stats(ledger)
    assert stats["claims"] == 2
    assert stats["llm_derived_claims"] == ["C2"]
    assert stats["primary_source_ratio"] == 0.5
