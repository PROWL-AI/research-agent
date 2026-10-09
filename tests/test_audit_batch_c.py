"""Batch-C audit fixes: MCP server lifecycle, run-id hygiene, Fabric bundle."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import research_agent.mcp_server as srv
from research_agent.agent.orchestrator import OrchestratorError
from research_agent.config import Config
from research_agent.evidence.store import (
    MAX_RUN_ID_LENGTH,
    ArtifactStore,
    Checkpoint,
    validate_run_id,
)

from conftest import FakeLLM, FakeProwl

DUMMY_CONFIG = Config(
    prowl_api_key="test",
    prowl_mcp_url="http://unused.invalid",
    llm_base_url="http://unused.invalid",
    llm_api_key="test",
    llm_model="cheap-model",
    llm_model_strong="strong-model",
)


@pytest.fixture
def wired(monkeypatch, mini_runbooks_dir, tmp_path, fake_llm, fake_prowl):
    monkeypatch.setattr("research_agent.runbook.RUNBOOKS_DIR", mini_runbooks_dir)
    monkeypatch.setenv("RESEARCH_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(srv, "_config_from_env", lambda: DUMMY_CONFIG)
    monkeypatch.setattr(srv, "_make_prowl", lambda config: fake_prowl)
    monkeypatch.setattr(srv, "_make_llm", lambda config: fake_llm)
    srv._TASKS.clear()
    yield srv
    srv._TASKS.clear()


def _one_step_plan() -> dict:
    return {
        "plan": [
            {"step": "baseline", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "a.com"}}
        ]
    }


def _checkpoint_on_disk(tmp_path: Path, run_id: str) -> dict:
    return json.loads((tmp_path / "runs" / run_id / "checkpoint.json").read_text())


class TestFinishedRunCheckpointIsUntouchable:
    async def test_rerun_with_finished_run_id_rejected_before_scheduling(
        self, wired, fake_llm: FakeLLM, tmp_path: Path
    ):
        fake_llm.plan_payload = _one_step_plan()
        result = await srv.research_run(
            "mini-teardown", {"competitors": ["a.com"]}, run_id="c1-done", wait=True
        )
        assert result["status"] == "complete"

        with pytest.raises(ValueError, match="already finished"):
            await srv.research_run(
                "mini-teardown", {"competitors": ["a.com"]}, run_id="c1-done"
            )
        assert _checkpoint_on_disk(tmp_path, "c1-done")["status"] == "complete"

    async def test_execute_run_failure_does_not_rewrite_finished_checkpoint(
        self, wired, fake_llm: FakeLLM, tmp_path: Path
    ):
        fake_llm.plan_payload = _one_step_plan()
        await srv.research_run(
            "mini-teardown", {"competitors": ["a.com"]}, run_id="c1-kept", wait=True
        )
        # Bypass the research_run pre-check: the orchestrator refuses the
        # finished id, and the blanket error handler must not mark it failed.
        with pytest.raises(OrchestratorError, match="already finished"):
            await srv._execute_run("mini-teardown", {"competitors": ["a.com"]}, "c1-kept", None)
        checkpoint = _checkpoint_on_disk(tmp_path, "c1-kept")
        assert checkpoint["status"] == "complete"
        assert checkpoint["stop_reason"] is None

    async def test_failed_run_marks_own_checkpoint_failed(
        self, wired, fake_llm: FakeLLM, tmp_path: Path
    ):
        fake_llm.plan_payload = {}  # planner contract violation -> run fails
        with pytest.raises(OrchestratorError):
            await srv.research_run(
                "mini-teardown", {"competitors": ["a.com"]}, run_id="c1-fail", wait=True
            )
        checkpoint = _checkpoint_on_disk(tmp_path, "c1-fail")
        assert checkpoint["status"] == "failed"
        assert checkpoint["stop_reason"]

    async def test_run_id_of_other_runbook_rejected(
        self, wired, fake_llm: FakeLLM, tmp_path: Path
    ):
        store = ArtifactStore(tmp_path / "runs" / "c1-other")
        store.save_checkpoint(Checkpoint(run_id="c1-other", runbook="mini-usd"))
        with pytest.raises(ValueError, match="already belongs to runbook 'mini-usd'"):
            await srv.research_run(
                "mini-teardown", {"competitors": ["a.com"]}, run_id="c1-other"
            )


class TestOrphanedRuns:
    async def test_startup_reconciliation_marks_running_interrupted(
        self, wired, tmp_path: Path
    ):
        store = ArtifactStore(tmp_path / "runs" / "c2-orphan")
        store.save_checkpoint(Checkpoint(run_id="c2-orphan", runbook="mini-teardown"))
        done = ArtifactStore(tmp_path / "runs" / "c2-done")
        finished = Checkpoint(run_id="c2-done", runbook="mini-teardown")
        finished.status = "complete"
        done.save_checkpoint(finished)

        srv._reconcile_orphaned_runs()

        orphan = _checkpoint_on_disk(tmp_path, "c2-orphan")
        assert orphan["status"] == "interrupted"
        assert orphan["partial"] is True
        assert orphan["stop_reason"] == "server restarted before completion"
        assert _checkpoint_on_disk(tmp_path, "c2-done")["status"] == "complete"

    def test_serve_reconciles_before_running(self, wired, tmp_path: Path, monkeypatch):
        store = ArtifactStore(tmp_path / "runs" / "c2-serve")
        store.save_checkpoint(Checkpoint(run_id="c2-serve", runbook="mini-teardown"))
        monkeypatch.setattr(srv.mcp, "run", lambda: None)

        srv.serve()

        assert _checkpoint_on_disk(tmp_path, "c2-serve")["status"] == "interrupted"

    async def test_get_status_flags_orphaned_running_checkpoint(
        self, wired, tmp_path: Path
    ):
        store = ArtifactStore(tmp_path / "runs" / "c2-flag")
        store.save_checkpoint(Checkpoint(run_id="c2-flag", runbook="mini-teardown"))

        status = await srv.research_get_status("c2-flag")
        assert status["status"] == "running"
        assert status["orphaned"] is True

    async def test_get_status_not_orphaned_while_task_alive(
        self, wired, tmp_path: Path
    ):
        store = ArtifactStore(tmp_path / "runs" / "c2-live")
        store.save_checkpoint(Checkpoint(run_id="c2-live", runbook="mini-teardown"))
        srv._TASKS["c2-live"] = asyncio.current_task()

        status = await srv.research_get_status("c2-live")
        assert status["status"] == "running"
        assert status["orphaned"] is False

    async def test_terminal_checkpoint_is_never_orphaned(
        self, wired, fake_llm: FakeLLM
    ):
        fake_llm.plan_payload = _one_step_plan()
        await srv.research_run(
            "mini-teardown", {"competitors": ["a.com"]}, run_id="c2-term", wait=True
        )
        status = await srv.research_get_status("c2-term")
        assert status["status"] == "complete"
        assert status["orphaned"] is False


class TestGetReportCheckpointAwareness:
    async def test_report_with_running_checkpoint_carries_mid_write_flag(
        self, wired, tmp_path: Path
    ):
        run_dir = tmp_path / "runs" / "c4-mid"
        ArtifactStore(run_dir).save_checkpoint(
            Checkpoint(run_id="c4-mid", runbook="mini-teardown")
        )
        (run_dir / "report.md").write_text("# partial draft\n", encoding="utf-8")

        report = await srv.research_get_report("c4-mid")
        assert report["report_markdown"] == "# partial draft\n"
        assert report["checkpoint_status"] == "running (report may be mid-write)"

    async def test_finished_run_report_has_no_mid_write_flag(
        self, wired, fake_llm: FakeLLM
    ):
        fake_llm.plan_payload = _one_step_plan()
        await srv.research_run(
            "mini-teardown", {"competitors": ["a.com"]}, run_id="c4-done", wait=True
        )
        report = await srv.research_get_report("c4-done")
        assert "checkpoint_status" not in report
        assert report["status"]["status"] == "complete"


class TestRunIdLengthLimit:
    def test_max_length_accepted(self):
        assert validate_run_id("a" * MAX_RUN_ID_LENGTH) == "a" * MAX_RUN_ID_LENGTH

    def test_over_limit_rejected(self):
        with pytest.raises(ValueError, match="128 characters max"):
            validate_run_id("a" * (MAX_RUN_ID_LENGTH + 1))

    async def test_over_limit_rejected_by_research_run(self, wired):
        with pytest.raises(ValueError, match="128 characters max"):
            await srv.research_run(
                "mini-teardown",
                {"competitors": ["a.com"]},
                run_id="a" * (MAX_RUN_ID_LENGTH + 1),
            )

    async def test_over_limit_rejected_by_get_status(self, wired):
        with pytest.raises(ValueError, match="128 characters max"):
            await srv.research_get_status("a" * (MAX_RUN_ID_LENGTH + 1))
