"""Round-3 audit fixes: resume money, crash disclosure, run locking,
skip-index namespaces, non-finite claim values, ledger schema versioning."""

from __future__ import annotations

import fcntl
import json
import math
import os
from pathlib import Path

import pytest

from research_agent.agent.orchestrator import Orchestrator, OrchestratorError, PlanItem
from research_agent.evidence.ledger import Ledger, LedgerError
from research_agent.evidence.store import ArtifactStore, Checkpoint

from conftest import FakeLLM, FakeProwl


def _plan(steps: int) -> dict:
    return {
        "plan": [
            {"step": f"step-{i}", "tool": "spyfu_get_domain_stats", "arguments": {"domain": f"x{i}.com"}}
            for i in range(steps)
        ]
    }


def _seed_checkpoint(runs: Path, run_id: str, **overrides) -> None:
    payload = {
        "run_id": run_id,
        "runbook": "mini-usd",
        "status": "running",
        "brief": {"competitors": ["a.com"]},
        "plan": _plan(3)["plan"],
        "completed_steps": [0],
        "counters": {"data_calls": 1, "attempted_calls": 1, "cost_usd": None},
    }
    payload.update(overrides)
    (runs / run_id).mkdir(parents=True, exist_ok=True)
    (runs / run_id / "checkpoint.json").write_text(json.dumps(payload))


# ── R1.1: resume must see the prior attempt's server cost ────────────────────

class TestResumeCostCarriesOver:
    async def test_persisted_cost_enforces_max_usd_across_resume(
        self, patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
    ):
        # mini-usd: max_usd=0.50. The crashed attempt already spent 0.45; a
        # fresh client must not restart the meter at zero.
        runs = tmp_path / "runs"
        _seed_checkpoint(runs, "r-cost", counters={
            "data_calls": 1, "attempted_calls": 1, "cost_usd": 0.45,
        })
        fake_prowl.cost_per_call = 0.10
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=runs)

        result = await orch.run("mini-usd", {"competitors": ["a.com"]}, run_id="r-cost")

        # Step 1 runs (0.45 → 0.55), then the budget stop lands: step 2 is
        # never attempted.
        assert len(fake_prowl.tool_calls) == 1
        assert result.partial is True
        assert any(
            s["index"] == 2 and "max_usd" in s["reason"] for s in result.skipped_steps
        )
        # The final cost is the whole run's spend, not this session's 0.10.
        assert result.stats["cost_usd"] == pytest.approx(0.55)

    async def test_persisted_cost_alone_can_stop_a_resume(
        self, patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
    ):
        runs = tmp_path / "runs"
        _seed_checkpoint(runs, "r-cost2", counters={
            "data_calls": 3, "attempted_calls": 3, "cost_usd": 0.60,
        })
        fake_prowl.cost_per_call = 0.10
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=runs)

        result = await orch.run("mini-usd", {"competitors": ["a.com"]}, run_id="r-cost2")

        assert len(fake_prowl.tool_calls) == 0
        assert result.partial is True
        assert result.stats["cost_usd"] == pytest.approx(0.60)

    async def test_fresh_run_is_not_seeded(
        self, patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
    ):
        fake_llm.plan_payload = _plan(1)
        fake_prowl.cost_per_call = 0.10
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")

        result = await orch.run("mini-usd", {"competitors": ["a.com"]}, run_id="r-fresh")

        assert result.status == "complete"
        assert result.stats["cost_usd"] == pytest.approx(0.10)


# ── R1.2: a crashed worker discloses every unreached step ────────────────────

class TestCrashDisclosure:
    async def test_crash_discloses_unreached_steps_without_completing_them(
        self, tmp_path: Path
    ):
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
        chunk = [(i, PlanItem(step=f"s{i}", tool="spyfu_get_domain_stats")) for i in range(3)]

        summaries = await run_data_segment(chunk, ctx, 1)

        assert [o.status for o in summaries[0].outcomes] == ["failed"] * 3
        skips = {s["index"]: s for s in checkpoint.skipped_steps}
        assert set(skips) == {0, 1, 2}
        assert all("worker crash" in s["reason"] for s in skips.values())
        # Not completed: a resume must re-execute them.
        assert checkpoint.completed_steps == []

    async def test_crash_skip_entries_are_reexecuted_on_resume(
        self, patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
    ):
        runs = tmp_path / "runs"
        _seed_checkpoint(
            runs, "r-cr", completed_steps=[0],
            skipped_steps=[
                {"index": 1, "step": "step-1", "tool": "spyfu_get_domain_stats",
                 "reason": "worker crash: boom", "kind": "runtime_skip"},
                {"index": 2, "step": "step-2", "tool": "spyfu_get_domain_stats",
                 "reason": "worker crash: boom", "kind": "runtime_skip"},
            ],
            partial=True, stop_reason="worker 0 crashed: boom",
        )
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=runs)

        result = await orch.run("mini-usd", {"competitors": ["a.com"]}, run_id="r-cr")

        assert len(fake_prowl.tool_calls) == 2
        assert result.status == "complete"
        assert all("worker crash" not in s["reason"] for s in result.skipped_steps)


# ── R1.3: one process per run_dir ────────────────────────────────────────────

class TestRunLock:
    async def test_locked_run_dir_is_rejected(
        self, patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
    ):
        run_dir = tmp_path / "runs" / "r-lock"
        run_dir.mkdir(parents=True)
        fd = os.open(run_dir / ".lock", os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            orch = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")
            with pytest.raises(OrchestratorError, match="locked by another process"):
                await orch.run("mini-usd", {"competitors": ["a.com"]}, run_id="r-lock")
        finally:
            os.close(fd)

    async def test_lock_is_released_when_the_run_ends(
        self, patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
    ):
        fake_llm.plan_payload = _plan(1)
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")
        await orch.run("mini-usd", {"competitors": ["a.com"]}, run_id="r-free")

        # The lock is free again — a rerun fails on the finished-run guard,
        # not on the lock.
        with pytest.raises(OrchestratorError, match="already finished"):
            await orch.run("mini-usd", {"competitors": ["a.com"]}, run_id="r-free")


# ── R1.4: plan drops and runtime skips live in different index spaces ────────

class TestSkipIndexNamespaces:
    async def test_plan_drop_does_not_suppress_runtime_skip_disclosure(
        self, patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
    ):
        # Raw plan: index 2 is dropped (tool not allowlisted), so the raw
        # index 2 and the validated-plan index 2 ('s3') collide numerically
        # while being different steps.
        fake_llm.plan_payload = {
            "plan": [
                {"step": "s0", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "a.com"}},
                {"step": "s1", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "b.com"}},
                {"step": "bad", "tool": "semrush_organic_keywords", "arguments": {}},
                {"step": "s3", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "c.com"}},
            ]
        }
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")

        # mini-teardown: max_tool_calls=2 → s3 (validated index 2) is
        # budget-skipped; the plan_drop at raw index 2 must not hide that.
        result = await orch.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r-ns")

        skips = result.skipped_steps
        assert any(
            s["index"] == 2 and s.get("kind") == "plan_drop" and s["step"] == "bad"
            for s in skips
        )
        assert any(
            s["index"] == 2 and s.get("kind") == "runtime_skip" and s["step"] == "s3"
            for s in skips
        )

    async def test_plan_drop_survives_the_resume_filter(
        self, patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
    ):
        runs = tmp_path / "runs"
        _seed_checkpoint(
            runs, "r-pd", completed_steps=[0],
            skipped_steps=[
                {"index": 3, "step": "bad", "tool": "semrush_organic_keywords",
                 "reason": "tool 'semrush_organic_keywords' is not in the runbook allowlist",
                 "kind": "plan_drop"},
            ],
        )
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=runs)

        result = await orch.run("mini-usd", {"competitors": ["a.com"]}, run_id="r-pd")

        plan_drops = [s for s in result.skipped_steps if s.get("kind") == "plan_drop"]
        assert len(plan_drops) == 1
        assert plan_drops[0]["step"] == "bad"


# ── R1.5: non-finite claim values are refused, persisted JSON stays strict ───

class TestNonFiniteClaims:
    def test_nan_value_is_rejected(self, tmp_path: Path):
        ledger = Ledger(tmp_path / "l.json")
        with pytest.raises(ValueError, match="finite"):
            ledger.add(claim="c", value=float("nan"), subject="s", source_tool="t")

    def test_infinity_value_is_rejected(self, tmp_path: Path):
        ledger = Ledger(tmp_path / "l.json")
        with pytest.raises(ValueError, match="finite"):
            ledger.add(claim="c", value=float("inf"), subject="s", source_tool="t")

    def test_saved_ledger_is_strict_json(self, tmp_path: Path):
        ledger = Ledger(tmp_path / "l.json")
        ledger.add(claim="c", value=5, unit="x", subject="s", source_tool="t")
        ledger.save()
        text = ledger.path.read_text()
        assert "NaN" not in text and "Infinity" not in text
        json.loads(text)

    async def test_extractor_nan_claim_does_not_falsely_verify_or_crash(
        self, patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
    ):
        # json.loads accepts a NaN literal from the extractor LLM; without the
        # validator two such claims would 'corroborate' each other ('nan' ==
        # 'nan') into a false verified status.
        fake_llm.plan_payload = _plan(2)
        fake_llm.claims_payload = {
            "claims": [
                {"claim": "traffic", "subject": "x.com traffic", "value": float("nan")},
            ]
        }
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")

        result = await orch.run("mini-usd", {"competitors": ["a.com"]}, run_id="r-nan")

        assert result.status == "complete"
        ledger = Ledger.load(Path(result.ledger_path))
        assert all(
            not (isinstance(c.value, float) and not math.isfinite(c.value))
            for c in ledger.claims
        )


# ── R1.7: ledger schema versioning and corrupt-file refusal ──────────────────

class TestLedgerSchemaVersion:
    def test_saved_ledger_carries_schema_version(self, tmp_path: Path):
        ledger = Ledger(tmp_path / "l.json")
        ledger.save()
        data = json.loads(ledger.path.read_text())
        assert data["schema_version"] == 1
        assert data["claims"] == []

    def test_dict_without_claims_key_is_not_an_empty_ledger(self, tmp_path: Path, caplog):
        path = tmp_path / "l.json"
        path.write_text(json.dumps({"something": "else"}))
        with pytest.raises(LedgerError, match="claims"):
            with caplog.at_level("WARNING", logger="research_agent.evidence.ledger"):
                Ledger.load(path)
        assert "no 'claims' key" in caplog.text

    def test_legacy_ledger_without_schema_version_loads(self, tmp_path: Path):
        path = tmp_path / "l.json"
        path.write_text(json.dumps({
            "claims": [{"id": "C1", "claim": "c", "source_tool": "t"}],
        }))
        ledger = Ledger.load(path)
        assert len(ledger.claims) == 1
