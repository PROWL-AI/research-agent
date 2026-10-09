"""Audit round 3, contract batch: restart-resume lifecycle, server refusal
envelopes, corrupt-checkpoint quarantine, prompt-injection isolation,
envelope metadata hygiene, idempotency-key plumbing."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from mcp.types import CallToolResult, TextContent

import research_agent.mcp_server as srv
from research_agent.agent.orchestrator import (
    _UNTRUSTED_CLOSE,
    _UNTRUSTED_OPEN,
    Orchestrator,
    PlanItem,
)
from research_agent.config import Config
from research_agent.evidence.ledger import Ledger
from research_agent.evidence.store import ArtifactStore, Checkpoint
from research_agent.prowl_client import ProwlClient, ToolCallError

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


def _checkpoint_on_disk(tmp_path: Path, run_id: str) -> dict:
    return json.loads((tmp_path / "runs" / run_id / "checkpoint.json").read_text())


def _two_step_plan() -> list[dict]:
    return [
        {"step": "baseline", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "a.com"}},
        {"step": "backlinks", "tool": "dataforseo_bl_summary", "arguments": {"target": "a.com"}},
    ]


def _seed_checkpoint(
    tmp_path: Path,
    run_id: str,
    status: str,
    plan: list[dict] | None = None,
    completed: list[int] | None = None,
) -> None:
    store = ArtifactStore(tmp_path / "runs" / run_id)
    checkpoint = Checkpoint(run_id=run_id, runbook="mini-teardown")
    checkpoint.status = status
    checkpoint.plan = plan if plan is not None else _two_step_plan()
    checkpoint.completed_steps = completed or []
    checkpoint.brief = {"competitors": ["a.com"]}
    checkpoint.partial = status in ("partial", "interrupted")
    if status == "interrupted":
        checkpoint.stop_reason = "server restarted before completion"
    store.save_checkpoint(checkpoint)


class EnvelopeProwl(ProwlClient):
    def __init__(self, payloads: list[Any]) -> None:
        super().__init__(api_key="test", mcp_url="http://unused.invalid")
        self.payloads = payloads
        self.rpc_calls: list[dict[str, Any]] = []

    async def _rpc(
        self, name: str, arguments: dict[str, Any] | None = None, *, retry: bool = True
    ) -> CallToolResult:
        self.rpc_calls.append({"tool": name, "arguments": arguments})
        payload = self.payloads[len(self.rpc_calls) - 1]
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload))])


class TestRestartResume:
    async def test_reconcile_marks_interrupted_not_partial(self, wired, tmp_path: Path):
        _seed_checkpoint(tmp_path, "r3-orphan", "running")

        srv._reconcile_orphaned_runs()

        checkpoint = _checkpoint_on_disk(tmp_path, "r3-orphan")
        assert checkpoint["status"] == "interrupted"
        assert checkpoint["stop_reason"] == "server restarted before completion"

    async def test_interrupted_run_resumes_via_research_run(
        self, wired, fake_prowl: FakeProwl, tmp_path: Path
    ):
        _seed_checkpoint(tmp_path, "r3-resume", "interrupted", completed=[0])

        result = await srv.research_run(
            "mini-teardown", {"competitors": ["a.com"]}, run_id="r3-resume", wait=True
        )

        assert result["status"] == "complete"
        # Only the step that never completed is re-executed (and re-billed).
        assert [call["name"] for call in fake_prowl.tool_calls] == ["dataforseo_bl_summary"]
        checkpoint = _checkpoint_on_disk(tmp_path, "r3-resume")
        assert checkpoint["status"] == "complete"
        assert checkpoint["completed_steps"] == [0, 1]

    async def test_failed_run_with_plan_resumes(
        self, wired, fake_prowl: FakeProwl, tmp_path: Path
    ):
        _seed_checkpoint(tmp_path, "r3-failed", "failed")

        result = await srv.research_run(
            "mini-teardown", {"competitors": ["a.com"]}, run_id="r3-failed", wait=True
        )

        assert result["status"] == "complete"
        assert [call["name"] for call in fake_prowl.tool_calls] == [
            "spyfu_get_domain_stats",
            "dataforseo_bl_summary",
        ]

    async def test_worker_sends_stable_per_step_idempotency_key(
        self, wired, fake_prowl: FakeProwl, tmp_path: Path
    ):
        _seed_checkpoint(tmp_path, "r3-idem", "interrupted")

        result = await srv.research_run(
            "mini-teardown", {"competitors": ["a.com"]}, run_id="r3-idem", wait=True
        )

        assert result["status"] == "complete"
        keys = [call["idempotency_key"] for call in fake_prowl.tool_calls]
        # One key per (step index, tool) — stable across a resume re-dispatch.
        assert sorted(keys) == [
            "r3-idem:0:spyfu_get_domain_stats",
            "r3-idem:1:dataforseo_bl_summary",
        ]

    async def test_partial_run_with_plan_resumes(
        self, wired, fake_prowl: FakeProwl, tmp_path: Path
    ):
        _seed_checkpoint(tmp_path, "r3-partial", "partial", completed=[0])

        result = await srv.research_run(
            "mini-teardown", {"competitors": ["a.com"]}, run_id="r3-partial", wait=True
        )

        assert result["status"] == "complete"
        assert [call["name"] for call in fake_prowl.tool_calls] == ["dataforseo_bl_summary"]

    async def test_complete_run_id_stays_terminal(
        self, wired, fake_llm: FakeLLM, tmp_path: Path
    ):
        fake_llm.plan_payload = {"plan": [_two_step_plan()[0]]}
        result = await srv.research_run(
            "mini-teardown", {"competitors": ["a.com"]}, run_id="r3-done", wait=True
        )
        assert result["status"] == "complete"

        with pytest.raises(ValueError, match="already finished"):
            await srv.research_run(
                "mini-teardown", {"competitors": ["a.com"]}, run_id="r3-done"
            )
        assert _checkpoint_on_disk(tmp_path, "r3-done")["status"] == "complete"

    async def test_interrupted_without_plan_replans_fresh(
        self, wired, fake_llm: FakeLLM, fake_prowl: FakeProwl, tmp_path: Path
    ):
        # The run died before planning finished: nothing was billed, so the
        # orchestrator re-plans over the empty run dir instead of stranding it.
        _seed_checkpoint(tmp_path, "r3-noplan", "interrupted", plan=[])
        fake_llm.plan_payload = {"plan": [_two_step_plan()[0]]}

        result = await srv.research_run(
            "mini-teardown", {"competitors": ["a.com"]}, run_id="r3-noplan", wait=True
        )

        assert result["status"] == "complete"
        assert [call["name"] for call in fake_prowl.tool_calls] == ["spyfu_get_domain_stats"]

    async def test_interrupted_status_visible_in_get_status(self, wired, tmp_path: Path):
        _seed_checkpoint(tmp_path, "r3-status", "interrupted", completed=[0])

        status = await srv.research_get_status("r3-status")

        assert status["status"] == "interrupted"
        assert status["stop_reason"] == "server restarted before completion"
        assert status["orphaned"] is False


class TestRefusalEnvelopes:
    async def test_success_false_envelope_raises_and_marks_record(self):
        client = EnvelopeProwl([
            {"success": False, "error_class": "tool_retired", "error": "retired 2026-09"}
        ])
        with pytest.raises(ToolCallError, match="tool_retired"):
            await client.call_tool("old_tool", {})
        record = client.call_log[-1]
        assert record.ok is False
        assert "tool_retired" in record.error

    async def test_error_class_key_alone_raises(self):
        client = EnvelopeProwl([{"error_class": "not_found", "error": "no such tool"}])
        with pytest.raises(ToolCallError, match="not_found"):
            await client.call_tool("ghost_tool", {})
        assert client.call_log[-1].ok is False

    async def test_insufficient_funds_raises_and_logs(self, caplog):
        client = EnvelopeProwl([
            {"success": False, "error_class": "insufficient_funds", "error": "balance 0.00"}
        ])
        with caplog.at_level(logging.ERROR, logger="research_agent.prowl_client"):
            with pytest.raises(ToolCallError, match="insufficient_funds"):
                await client.call_tool("spyfu_get_domain_stats", {"domain": "x.com"})
        assert "insufficient_funds" in caplog.text
        assert "wallet" in caplog.text

    async def test_success_true_envelope_is_ok(self):
        client = EnvelopeProwl([{"success": True, "result": {"rows": [1]}}])
        payload = await client.call_tool("some_tool", {})
        assert payload["success"] is True
        assert client.call_log[-1].ok is True

    async def test_refused_step_does_not_become_done(
        self, wired, fake_prowl: FakeProwl, fake_llm: FakeLLM, tmp_path: Path
    ):
        fake_llm.plan_payload = {"plan": [_two_step_plan()[0]]}
        fake_prowl.error_envelopes["spyfu_get_domain_stats"] = {
            "success": False,
            "error_class": "validation",
            "error": "bad params",
        }

        result = await srv.research_run(
            "mini-teardown", {"competitors": ["a.com"]}, run_id="r3-refused", wait=True
        )

        assert result["status"] == "partial"
        checkpoint = _checkpoint_on_disk(tmp_path, "r3-refused")
        assert "validation" in checkpoint["stop_reason"]
        # The refused step is disclosed, not completed: it stays resumable.
        assert 0 not in checkpoint["completed_steps"]
        assert checkpoint["skipped_steps"][0]["tool"] == "spyfu_get_domain_stats"

    async def test_insufficient_funds_stops_run_honestly(
        self, wired, fake_prowl: FakeProwl, fake_llm: FakeLLM, tmp_path: Path
    ):
        fake_llm.plan_payload = {"plan": _two_step_plan()}
        fake_prowl.error_envelopes["spyfu_get_domain_stats"] = {
            "success": False,
            "error_class": "insufficient_funds",
            "error": "balance 0.00",
        }

        result = await srv.research_run(
            "mini-teardown", {"competitors": ["a.com"]}, run_id="r3-broke", wait=True
        )

        assert result["status"] == "partial"
        checkpoint = _checkpoint_on_disk(tmp_path, "r3-broke")
        assert "insufficient_funds" in checkpoint["stop_reason"]
        assert checkpoint["counters"]["data_calls"] == 0


class TestCorruptCheckpointQuarantine:
    def test_reconcile_skips_corrupt_checkpoint(self, wired, tmp_path: Path):
        corrupt_dir = tmp_path / "runs" / "r3-corrupt"
        corrupt_dir.mkdir(parents=True)
        (corrupt_dir / "checkpoint.json").write_text("{not json", encoding="utf-8")
        _seed_checkpoint(tmp_path, "r3-healthy", "running")

        srv._reconcile_orphaned_runs()

        assert _checkpoint_on_disk(tmp_path, "r3-healthy")["status"] == "interrupted"

    def test_serve_starts_with_corrupt_checkpoint(self, wired, tmp_path: Path, monkeypatch):
        corrupt_dir = tmp_path / "runs" / "r3-corrupt"
        corrupt_dir.mkdir(parents=True)
        (corrupt_dir / "checkpoint.json").write_text('{"run_id": 42', encoding="utf-8")
        monkeypatch.setattr(srv.mcp, "run", lambda: None)

        srv.serve()

    async def test_get_status_names_corrupt_checkpoint(self, wired, tmp_path: Path):
        corrupt_dir = tmp_path / "runs" / "r3-corrupt"
        corrupt_dir.mkdir(parents=True)
        (corrupt_dir / "checkpoint.json").write_text("{not json", encoding="utf-8")

        with pytest.raises(ValueError, match="checkpoint corrupt"):
            await srv.research_get_status("r3-corrupt")


class TestPromptInjectionIsolation:
    async def test_transform_prompt_wraps_artifacts_untrusted(
        self, fake_prowl: FakeProwl, fake_llm: FakeLLM, tmp_path: Path
    ):
        store = ArtifactStore(tmp_path / "run")
        store.save_raw(0, "spyfu_get_domain_stats", {"traffic": 1000})
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path)
        item = PlanItem(step="synthesize", tool="transform", instruction="sum it up")

        await orch._run_transform(item, store)

        call = fake_llm.calls[-1]
        system, user = call["messages"][0]["content"], call["messages"][1]["content"]
        assert _UNTRUSTED_OPEN in user and _UNTRUSTED_CLOSE in user
        assert "untrusted scraped data" in system

    async def test_extract_claims_prompt_wraps_raw_result(
        self, fake_prowl: FakeProwl, fake_llm: FakeLLM, tmp_path: Path
    ):
        store = ArtifactStore(tmp_path / "run")
        raw_path = store.save_raw(0, "tool", {"x": 1})
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path)
        item = PlanItem(step="baseline", tool="spyfu_get_domain_stats")
        ledger = Ledger.load(store.run_dir / "ledger.json")

        await orch._extract_claims(item, {"rows": [{"value": 42}]}, raw_path, ledger)

        call = fake_llm.calls[-1]
        system, user = call["messages"][0]["content"], call["messages"][1]["content"]
        assert _UNTRUSTED_OPEN in user and _UNTRUSTED_CLOSE in user
        assert user.index(_UNTRUSTED_OPEN) < user.index("rows") < user.index(_UNTRUSTED_CLOSE)
        assert "untrusted scraped data" in system


class TestEnvelopeHygiene:
    async def test_claim_extractor_never_sees_billing_meta(
        self, fake_prowl: FakeProwl, fake_llm: FakeLLM, tmp_path: Path
    ):
        store = ArtifactStore(tmp_path / "run")
        raw_path = store.save_raw(0, "tool", {"x": 1})
        orch = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path)
        item = PlanItem(step="baseline", tool="spyfu_get_domain_stats")
        ledger = Ledger.load(store.run_dir / "ledger.json")
        payload = {
            "result": {"rows": [{"value": 42}]},
            "billing": {"actual_cost_usd": 0.01},
            "execution_time_ms": 321,
            "billing_warning": "low balance",
        }

        await orch._extract_claims(item, payload, raw_path, ledger)

        user = fake_llm.calls[-1]["messages"][1]["content"]
        assert "rows" in user
        assert "billing" not in user
        assert "execution_time_ms" not in user

    async def test_billing_warning_recorded_not_dropped(self):
        client = EnvelopeProwl([
            {"result": {"rows": [1]}, "billing_warning": "wallet below $1"}
        ])
        await client.call_tool("some_tool", {})
        record = client.call_log[-1]
        assert record.ok is True
        assert record.warning == "wallet below $1"


class TestIdempotencyKey:
    async def test_idempotency_key_sent_in_request(self):
        client = EnvelopeProwl([{"result": {"rows": []}}])
        await client.call_tool("bar_tool", {"domain": "x.com"}, idempotency_key="run-1:step-3")
        assert client.rpc_calls[0]["arguments"] == {
            "tool_name": "bar_tool",
            "params": {"domain": "x.com"},
            "idempotency_key": "run-1:step-3",
        }

    async def test_no_idempotency_key_by_default(self):
        client = EnvelopeProwl([{"result": {"rows": []}}])
        await client.call_tool("bar_tool", {"domain": "x.com"})
        assert "idempotency_key" not in client.rpc_calls[0]["arguments"]
