"""Batch-A audit fixes: money, resume integrity, atomic persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent.agent.orchestrator import Orchestrator, OrchestratorError, validate_plan
from research_agent.evidence.ledger import Ledger
from research_agent.evidence.store import ArtifactStore, Checkpoint

from conftest import FakeLLM, FakeProwl


def _plan(steps: int) -> dict:
    return {
        "plan": [
            {"step": f"step-{i}", "tool": "spyfu_get_domain_stats", "arguments": {"domain": f"x{i}.com"}}
            for i in range(steps)
        ]
    }


class TestFinishedRunIdIsNotReusable:
    async def test_rerun_over_complete_run_raises(
        self, patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
    ):
        fake_llm.plan_payload = _plan(1)
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")
        result = await orch.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r-done")
        assert result.status == "complete"

        with pytest.raises(OrchestratorError, match="already finished"):
            await orch.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r-done")

    async def test_rerun_over_partial_run_raises(
        self, patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
    ):
        fake_llm.plan_payload = _plan(3)
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")
        result = await orch.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r-part")
        assert result.status == "partial"

        with pytest.raises(OrchestratorError, match="already finished"):
            await orch.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r-part")


class TestFailedCallsSpendTheBudget:
    async def test_failed_dispatch_counts_as_attempted(
        self, patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
    ):
        fake_prowl.fail_on.add("spyfu_get_domain_stats")
        fake_llm.plan_payload = {
            "plan": [
                {"step": "s0", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "a.com"}, "on_error_skip": True},
                {"step": "s1", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "b.com"}, "on_error_skip": True},
                {"step": "s2", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "c.com"}, "on_error_skip": True},
            ]
        }
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")

        result = await orch.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r-fail")

        # budget max_tool_calls=2: two failed (billed) attempts exhaust it even
        # though zero succeeded — the third step is never attempted.
        assert result.partial is True
        assert len(fake_prowl.tool_calls) == 2
        assert result.stats["attempted_calls"] == 2
        assert result.stats["data_calls"] == 0


class TestPlanValidationReportsDrops:
    def test_duplicate_steps_are_dropped_and_reported(self):
        valid, dropped = validate_plan(
            [
                {"step": "a", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "x.com"}},
                {"step": "b", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "x.com"}},
            ],
            allowlist=["spyfu_get_domain_stats"],
            catalog=["spyfu_get_domain_stats"],
        )
        assert [item.step for item in valid] == ["a"]
        assert dropped[0]["step"] == "b"
        assert "duplicate" in dropped[0]["reason"]

    def test_case_drift_is_normalised_not_dropped(self):
        valid, dropped = validate_plan(
            [{"step": "a", "tool": "SpyFu_Get_Domain_Stats", "arguments": {}}],
            allowlist=["spyfu_get_domain_stats"],
            catalog=["spyfu_get_domain_stats"],
        )
        assert dropped == []
        assert valid[0].tool == "spyfu_get_domain_stats"

    def test_transform_cap(self):
        valid, dropped = validate_plan(
            [{"step": f"t{i}", "tool": "transform", "instruction": "x"} for i in range(30)],
            allowlist=[],
            catalog=[],
        )
        assert len(valid) == 25
        assert len(dropped) == 5


class TestAtomicPersistence:
    def test_checkpoint_write_leaves_no_partial_file(self, tmp_path: Path):
        store = ArtifactStore(tmp_path / "run1")
        checkpoint = Checkpoint(run_id="run1", runbook="x")
        store.save_checkpoint(checkpoint)
        assert store.checkpoint_path.is_file()
        assert not (tmp_path / "run1" / "checkpoint.json.tmp").exists()
        loaded = store.load_checkpoint()
        assert loaded is not None and loaded.run_id == "run1"

    def test_ledger_write_leaves_no_partial_file(self, tmp_path: Path):
        ledger = Ledger(tmp_path / "run1" / "ledger.json")
        ledger.add(claim="x has 5 visitors", value=5, unit="visitors", source_tool="t")
        ledger.save()
        assert not (tmp_path / "run1" / "ledger.json.tmp").exists()
        reloaded = Ledger.load(ledger.path)
        assert len(reloaded.claims) == 1


class TestLedgerCorroboration:
    def test_same_metric_different_wording_corroborates(self, tmp_path: Path):
        ledger = Ledger(tmp_path / "l.json")
        ledger.add(
            claim="example.com traffic", value=100, unit="visitors",
            subject="example.com monthly organic traffic", source_tool="tool_a",
        )
        second = ledger.add(
            claim="example.com traffic", value=100, unit="visitors",
            subject="example.com organic traffic monthly", source_tool="tool_b",
        )
        assert second.status.value == "verified"

    def test_same_number_different_unit_is_a_conflict(self, tmp_path: Path):
        ledger = Ledger(tmp_path / "l.json")
        ledger.add(claim="c", value=5, unit="%", subject="s metric", source_tool="tool_a")
        second = ledger.add(claim="c", value=5, unit="M", subject="s metric", source_tool="tool_b")
        assert second.status.value == "conflict"

    def test_verbatim_keeps_verified_through_a_conflict(self, tmp_path: Path):
        ledger = Ledger(tmp_path / "l.json")
        first = ledger.add(claim='"great product"', subject="s reviews", source_tool="tool_a", verbatim=True)
        assert first.status.value == "verified"
        ledger.add(claim="different value", value=1, unit="x", subject="s reviews", source_tool="tool_b")
        assert first.status.value == "verified"
