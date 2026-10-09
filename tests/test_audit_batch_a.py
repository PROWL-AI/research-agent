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

    async def test_rerun_over_partial_run_resumes_failed_steps(
        self, patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
    ):
        # A partial run is resumable: the hard-failed step was never marked
        # completed, so resume re-executes it instead of erroring out.
        fake_llm.plan_payload = _plan(3)
        fake_prowl.fail_on.add("spyfu_get_domain_stats")
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")
        result = await orch.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r-part")
        assert result.status == "partial"

        fake_prowl.fail_on.clear()
        fake_prowl.tool_calls.clear()
        orch2 = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")
        resumed = await orch2.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r-part")

        # Only step-0 (the failed one) re-runs; steps 1-2 were completed by
        # the first attempt and are never re-billed.
        assert [c["arguments"]["domain"] for c in fake_prowl.tool_calls] == ["x0.com"]
        checkpoint = json.loads(
            (tmp_path / "runs" / "r-part" / "checkpoint.json").read_text()
        )
        assert checkpoint["stop_reason"] is None
        assert 0 in checkpoint["completed_steps"]
        # Steps 1-2 never produced data, so the run stays honestly partial.
        assert resumed.status == "partial"


class TestCrashResumeClearsStopReason:
    async def test_persisted_stop_reason_does_not_skip_remaining_steps(
        self, patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
    ):
        # Crash mid-run: the checkpoint still says "running" but carries the
        # dead attempt's stop_reason and skip disclosures. Resume must clear
        # both and re-execute the non-completed steps.
        runs = tmp_path / "runs"
        (runs / "r-crash").mkdir(parents=True)
        (runs / "r-crash" / "checkpoint.json").write_text(json.dumps({
            "run_id": "r-crash",
            "runbook": "mini-usd",
            "status": "running",
            "brief": {"competitors": ["a.com"]},
            "plan": _plan(3)["plan"],
            "completed_steps": [0],
            "skipped_steps": [
                {"index": 1, "step": "step-1", "tool": "spyfu_get_domain_stats",
                 "reason": "worker 0 crashed: boom"}
            ],
            "partial": True,
            "stop_reason": "worker 0 crashed: boom",
            "counters": {"data_calls": 1, "attempted_calls": 1, "cost_usd": None},
        }))
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=runs)

        result = await orch.run("mini-usd", {"competitors": ["a.com"]}, run_id="r-crash")

        assert len(fake_prowl.tool_calls) == 2  # steps 1 and 2 re-executed
        assert result.status == "complete"
        # The stale crash disclosure for step-1 is gone — it completed.
        assert all(s["index"] != 1 for s in result.skipped_steps)
        checkpoint = json.loads((runs / "r-crash" / "checkpoint.json").read_text())
        assert checkpoint["stop_reason"] is None


class TestResumeInputHandling:
    def _seed_checkpoint(self, runs: Path, run_id: str) -> None:
        (runs / run_id).mkdir(parents=True)
        (runs / run_id / "checkpoint.json").write_text(json.dumps({
            "run_id": run_id,
            "runbook": "mini-usd",
            "status": "running",
            "brief": {"competitors": ["a.com"]},
            "plan": _plan(1)["plan"],
            "completed_steps": [],
            "counters": {"data_calls": 0, "cost_usd": None},
        }))

    async def test_resume_warns_on_mismatched_inputs_and_uses_checkpoint_brief(
        self, patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl, caplog
    ):
        runs = tmp_path / "runs"
        self._seed_checkpoint(runs, "r-mix")
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=runs)

        with caplog.at_level("WARNING", logger="research_agent.agent.orchestrator"):
            result = await orch.run("mini-usd", {"competitors": ["b.com"]}, run_id="r-mix")

        assert result.status == "complete"
        assert "differ from the checkpoint brief" in caplog.text
        writer_call = next(
            c for c in fake_llm.calls if c["tier"] == "strong" and not c["json_mode"]
        )
        assert "a.com" in writer_call["messages"][1]["content"]
        assert "b.com" not in writer_call["messages"][1]["content"]

    async def test_resume_skips_input_validation_entirely(
        self, patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
    ):
        # Inputs that a fresh run would reject (unknown keys) must not kill a
        # resume — they are ignored in favour of the checkpoint's brief.
        runs = tmp_path / "runs"
        self._seed_checkpoint(runs, "r-bogus")
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=runs)

        result = await orch.run("mini-usd", {"bogus": "x"}, run_id="r-bogus")

        assert result.status == "complete"
        assert len(fake_prowl.tool_calls) == 1


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


class TestLedgerValuelessClaims:
    def test_verbatim_quote_does_not_conflict_with_numeric_claim(self, tmp_path: Path):
        ledger = Ledger(tmp_path / "l.json")
        quote = ledger.add(
            claim='"traffic grew a lot"', subject="s traffic",
            source_tool="tool_a", verbatim=True,
        )
        numeric = ledger.add(
            claim="s traffic is 42000", value=42000, unit="visits",
            subject="s traffic", source_tool="tool_b",
        )
        assert quote.status.value == "verified"
        assert numeric.status.value != "conflict"

    def test_numeric_claim_does_not_conflict_with_valueless_peer(self, tmp_path: Path):
        ledger = Ledger(tmp_path / "l.json")
        ledger.add(
            claim="s traffic is 42000", value=42000, unit="visits",
            subject="s traffic", source_tool="tool_a",
        )
        quote = ledger.add(
            claim='"traffic grew a lot"', subject="s traffic",
            source_tool="tool_b", verbatim=True,
        )
        assert quote.status.value == "verified"

    def test_new_verbatim_entry_stays_verified_inside_a_conflict(self, tmp_path: Path):
        ledger = Ledger(tmp_path / "l.json")
        ledger.add(claim="c", value=5, unit="%", subject="s metric", source_tool="tool_a")
        conflicted = ledger.add(claim="c", value=9, unit="%", subject="s metric", source_tool="tool_b")
        assert conflicted.status.value == "conflict"
        quote = ledger.add(
            claim='"about five percent"', subject="s metric",
            source_tool="tool_c", verbatim=True,
        )
        assert quote.status.value == "verified"

    def test_valued_conflicts_still_fire(self, tmp_path: Path):
        ledger = Ledger(tmp_path / "l.json")
        first = ledger.add(claim="c", value=5, unit="%", subject="s metric", source_tool="tool_a")
        second = ledger.add(claim="c", value=9, unit="%", subject="s metric", source_tool="tool_b")
        assert first.status.value == "conflict"
        assert second.status.value == "conflict"


class TestSingleWorkerCrash:
    async def test_unexpected_worker_error_becomes_a_failed_summary(self, tmp_path: Path):
        from research_agent.agent.orchestrator import PlanItem
        from research_agent.agent.subagent import WorkerContext, run_data_segment

        class BoomOrch:
            prowl = None

            @staticmethod
            def _budget_stop_reason(budget, checkpoint):
                raise RuntimeError("boom")

        checkpoint = Checkpoint(run_id="x", runbook="mini-teardown")
        ctx = WorkerContext(
            orch=BoomOrch(),
            checkpoint=checkpoint,
            store=ArtifactStore(tmp_path / "x"),
            ledger=Ledger(tmp_path / "x" / "ledger.json"),
            budget=None,
        )

        summaries = await run_data_segment(
            [(0, PlanItem(step="s0", tool="spyfu_get_domain_stats"))], ctx, 1
        )

        assert checkpoint.partial is True
        assert "boom" in checkpoint.stop_reason
        assert summaries[0].outcomes[0].status == "failed"
        assert "boom" in summaries[0].outcomes[0].note


class TestAtomicReportWrite:
    async def test_report_md_write_leaves_no_partial_file(
        self, patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
    ):
        fake_llm.plan_payload = _plan(1)
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")
        result = await orch.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r-atom")

        run_dir = tmp_path / "runs" / "r-atom"
        assert Path(result.report_path).is_file()
        assert not (run_dir / "report.md.tmp").exists()
        assert Path(result.report_path).read_text() == fake_llm.report_text
