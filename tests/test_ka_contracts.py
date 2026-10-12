"""KA contract tests that the remediation waves turn green, one wave at a time.

Wave 1 (W1-T1, run ownership): KA-06 — a process that does not hold a run's
lock must never write that run's checkpoint. Ported from
docs/reports/2026-10-10-agent-deep-audit/raw/probe_agent_contracts.py; the
other KA probes land with waves 2-3.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

import research_agent.mcp_server as srv
from research_agent.agent.orchestrator import Orchestrator, OrchestratorError
from research_agent.config import Config
from research_agent.evidence.store import ArtifactStore, Checkpoint

from conftest import FakeLLM, FakeProwl, hold_run_lock

TOOL = "spyfu_get_domain_stats"
BRIEF = {"competitors": ["example.com"]}


def steps(count: int = 1) -> dict:
    return {"plan": [
        {"step": f"baseline-{i}", "tool": TOOL, "arguments": {"domain": f"sample-{i}.example.com"}}
        for i in range(count)
    ]}


@pytest.fixture
def wired(monkeypatch, patched_runbooks, tmp_path):
    monkeypatch.setenv("RESEARCH_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("RESEARCH_NO_SUBAGENTS", "1")
    config = Config(
        prowl_api_key="test", prowl_mcp_url="http://unused.invalid",
        llm_api_key="test", llm_base_url="http://unused.invalid",
        llm_model="cheap", llm_model_strong="strong",
    )
    monkeypatch.setattr(srv, "_config_from_env", lambda: config)
    monkeypatch.setattr(srv, "_make_prowl", lambda config: FakeProwl())
    monkeypatch.setattr(srv, "_make_llm", lambda config: FakeLLM())
    srv._TASKS.clear()
    yield tmp_path / "runs"
    srv._TASKS.clear()


# ── KA-06: a non-owner cannot mutate a locked checkpoint ─────────────────────

@pytest.mark.parametrize("entry", ["run", "startup"])
async def test_ka06_non_owner_cannot_mutate_locked_checkpoint(wired, entry):
    store = ArtifactStore(wired / "active-owner")
    store.save_checkpoint(Checkpoint(run_id="active-owner", runbook="mini-teardown"))
    before = store.checkpoint_path.read_bytes()
    with hold_run_lock(store.run_dir):
        if entry == "run":
            with pytest.raises(OrchestratorError, match="locked by another process"):
                await srv.research_run("mini-teardown", BRIEF, "active-owner", wait=True)
        else:
            srv._reconcile_orphaned_runs()
        assert store.checkpoint_path.read_bytes() == before


def test_control_unlocked_orphan_is_reconciled(wired):
    store = ArtifactStore(wired / "orphan-control")
    store.save_checkpoint(Checkpoint(run_id="orphan-control", runbook="mini-teardown"))
    srv._reconcile_orphaned_runs()
    checkpoint = store.load_checkpoint()
    assert checkpoint.status == "interrupted"
    assert checkpoint.partial is True
    assert checkpoint.terminal_code == "interrupted"
    assert checkpoint.stop_reason == "process exited before completion"


def test_reconcile_orphans_reports_what_it_marked_and_skips_active(wired, caplog):
    from research_agent.evidence.runlock import reconcile_orphans

    orphan = ArtifactStore(wired / "orphan")
    orphan.save_checkpoint(Checkpoint(run_id="orphan", runbook="mini-teardown"))
    active = ArtifactStore(wired / "active")
    active.save_checkpoint(Checkpoint(run_id="active", runbook="mini-teardown"))
    before = active.checkpoint_path.read_bytes()
    with hold_run_lock(active.run_dir), caplog.at_level(logging.INFO):
        marked = reconcile_orphans(wired)
    assert marked == ["orphan"]
    assert active.checkpoint_path.read_bytes() == before
    text = caplog.text
    assert "event=run.reconcile.skipped_active" in text and "run_id=active" in text
    assert "event=run.reconcile.interrupted" in text and "run_id=orphan" in text


def test_reconcile_orphans_skips_corrupt_and_missing_root(tmp_path):
    from research_agent.evidence.runlock import reconcile_orphans

    assert reconcile_orphans(tmp_path / "absent") == []
    corrupt = tmp_path / "runs" / "corrupt"
    corrupt.mkdir(parents=True)
    (corrupt / "checkpoint.json").write_text("{not json", encoding="utf-8")
    assert reconcile_orphans(tmp_path / "runs") == []
    assert (corrupt / "checkpoint.json").read_text(encoding="utf-8") == "{not json"


# ── The owner writes every lifecycle state while live ────────────────────────

class BlockingProwl(FakeProwl):
    """call_tool parks until released, so a test can act while a run is live."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def call_tool(self, name, arguments, idempotency_key=None):
        self.entered.set()
        await self.release.wait()
        return await super().call_tool(name, arguments, idempotency_key)


async def test_cancel_mid_run_is_written_by_the_owner_and_non_owners_write_nothing(wired):
    from research_agent.evidence.runlock import is_locked_elsewhere, reconcile_orphans

    prowl = BlockingProwl()
    llm = FakeLLM()
    llm.plan_payload = steps()
    orch = Orchestrator(prowl, llm, runs_root=wired)
    task = asyncio.create_task(orch.run("mini-teardown", BRIEF, run_id="live"))
    await asyncio.wait_for(prowl.entered.wait(), timeout=10)

    store = ArtifactStore(wired / "live")
    before = store.checkpoint_path.read_bytes()
    assert store.load_checkpoint().status == "running"
    assert is_locked_elsewhere(store.run_dir)

    # Non-owner exception path: a second run on the same id is refused and
    # writes nothing — neither through the orchestrator nor through MCP.
    with pytest.raises(OrchestratorError, match="locked by another process"):
        await Orchestrator(FakeProwl(), FakeLLM(), runs_root=wired).run(
            "mini-teardown", BRIEF, run_id="live"
        )
    with pytest.raises(OrchestratorError, match="locked by another process"):
        await srv.research_run("mini-teardown", BRIEF, "live", wait=True)
    # Non-owner cancel path: a refused attempt cancelled mid-flight is still a
    # non-owner — nothing it does reaches the live checkpoint.
    refused = asyncio.create_task(srv.research_run("mini-teardown", BRIEF, "live", wait=True))
    await asyncio.sleep(0)
    refused.cancel()
    with pytest.raises((asyncio.CancelledError, OrchestratorError)):
        await refused
    assert reconcile_orphans(wired) == []
    assert store.checkpoint_path.read_bytes() == before

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    checkpoint = store.load_checkpoint()
    assert checkpoint.status == "partial"
    assert checkpoint.partial is True
    assert checkpoint.stop_reason == "cancelled"
    assert checkpoint.terminal_code == "cancelled"
    # The lock is released only after the terminal write.
    assert not is_locked_elsewhere(store.run_dir)


async def test_owner_writes_failed_on_exception(wired):
    class ExplodingLLM(FakeLLM):
        async def complete(self, messages, tier="cheap", json_mode=False, **kwargs):
            raise RuntimeError("planner exploded")

    with pytest.raises(RuntimeError, match="planner exploded"):
        await Orchestrator(FakeProwl(), ExplodingLLM(), runs_root=wired).run(
            "mini-teardown", BRIEF, run_id="boom"
        )
    checkpoint = ArtifactStore(wired / "boom").load_checkpoint()
    assert checkpoint.status == "failed"
    assert checkpoint.stop_reason == "planner exploded"
    assert checkpoint.terminal_code == "error"


async def test_checkpoint_exists_before_planning(wired):
    class SlowPlanner(FakeLLM):
        def __init__(self) -> None:
            super().__init__()
            self.planning = asyncio.Event()
            self.go = asyncio.Event()

        async def complete(self, messages, tier="cheap", json_mode=False, **kwargs):
            if tier == "strong" and json_mode:
                self.planning.set()
                await self.go.wait()
            return await super().complete(messages, tier, json_mode, **kwargs)

    llm = SlowPlanner()
    llm.plan_payload = steps()
    task = asyncio.create_task(
        Orchestrator(FakeProwl(), llm, runs_root=wired).run("mini-teardown", BRIEF, run_id="early")
    )
    await asyncio.wait_for(llm.planning.wait(), timeout=10)
    status = srv._status_dict("early")
    assert status["status"] == "running" and status["terminal_code"] is None
    llm.go.set()
    result = await task
    assert result.status == "complete" and result.terminal_code == "completed"


async def test_failure_before_the_orchestrator_leaves_no_ghost_checkpoint(wired, monkeypatch):
    def broken_prowl(config):
        raise RuntimeError("cannot build client")

    monkeypatch.setattr(srv, "_make_prowl", broken_prowl)
    handle = await srv.research_run("mini-teardown", BRIEF, run_id="pre-fail")
    assert handle == {"run_id": "pre-fail", "status": "running"}
    with pytest.raises(RuntimeError):
        await srv._TASKS["pre-fail"]
    assert not (wired / "pre-fail" / "checkpoint.json").exists()
    status = await srv.research_get_status("pre-fail")
    assert status["status"] == "failed"
    assert status["terminal_code"] == "error"
    assert "cannot build client" in status["stop_reason"]
    assert status["has_checkpoint"] is False


# ── terminal_code on every terminal write ────────────────────────────────────

async def test_clean_finish_is_completed_everywhere(wired, capsys, monkeypatch):
    llm = FakeLLM()
    llm.plan_payload = steps()
    monkeypatch.setattr(srv, "_make_llm", lambda config: llm)
    result = await srv.research_run("mini-teardown", BRIEF, run_id="clean", wait=True)
    assert result["status"] == "complete"
    assert result["terminal_code"] == "completed"
    status = await srv.research_get_status("clean")
    assert status["terminal_code"] == "completed"
    assert status["has_checkpoint"] is True

    from research_agent.__main__ import main

    assert main(["status", "clean"]) == 0
    assert "terminal: completed" in capsys.readouterr().out


async def test_budget_stop_maps_to_budget_code(wired):
    llm = FakeLLM()
    llm.plan_payload = steps(3)  # mini-teardown allows 2 tool calls
    result = await Orchestrator(FakeProwl(), llm, runs_root=wired).run(
        "mini-teardown", BRIEF, run_id="budget"
    )
    assert result.status == "partial"
    assert result.terminal_code == "budget_tools"
    assert ArtifactStore(wired / "budget").load_checkpoint().terminal_code == "budget_tools"


async def test_hard_step_failure_maps_to_step_failed(wired):
    prowl = FakeProwl()
    prowl.fail_on = {TOOL}
    llm = FakeLLM()
    llm.plan_payload = steps()
    result = await Orchestrator(prowl, llm, runs_root=wired).run(
        "mini-teardown", BRIEF, run_id="stepfail"
    )
    assert result.status == "partial"
    assert result.terminal_code == "step_failed"


def test_terminal_code_mapping_is_closed():
    from research_agent.evidence import terminal

    assert terminal.TERMINAL_CODES == frozenset({
        "completed", "budget_tools", "budget_usd", "budget_minutes", "budget_llm",
        "step_failed", "evidence_incomplete", "cancelled", "error", "interrupted",
    })
    assert terminal.code_for_stop_reason(None) == "completed"
    assert terminal.code_for_stop_reason("max_tool_calls=2") == "budget_tools"
    assert terminal.code_for_stop_reason("max_usd=0.5") == "budget_usd"
    assert terminal.code_for_stop_reason("max_usd=0.5 (estimated from catalog prices)") == "budget_usd"
    assert terminal.code_for_stop_reason("max_minutes=30") == "budget_minutes"
    assert terminal.code_for_stop_reason("step 'x' failed: boom") == "step_failed"
    assert terminal.code_for_stop_reason("worker 1 crashed: boom") == "step_failed"


def test_old_checkpoint_without_terminal_code_loads(tmp_path):
    run_dir = tmp_path / "old"
    run_dir.mkdir()
    (run_dir / "checkpoint.json").write_text(
        json.dumps({"run_id": "old", "runbook": "mini-teardown", "status": "complete"}),
        encoding="utf-8",
    )
    checkpoint = ArtifactStore(run_dir).load_checkpoint()
    assert checkpoint.terminal_code is None
    assert checkpoint.migrated_from == 1  # v1 files load through the v1 → v2 migration


# ── rewrite_report never writes over a live run ──────────────────────────────

async def test_rewrite_report_refused_while_locked(wired, fake_llm):
    from research_agent.evidence.ledger import Ledger

    store = ArtifactStore(wired / "rw-live")
    store.save_checkpoint(Checkpoint(run_id="rw-live", runbook="mini-teardown", brief=BRIEF))
    Ledger(store.run_dir / "ledger.json").save()
    before = store.checkpoint_path.read_bytes()

    from research_agent.agent.writer import rewrite_report

    with hold_run_lock(store.run_dir):
        with pytest.raises(OrchestratorError, match="is active; rewrite refused"):
            await rewrite_report(fake_llm, wired, "rw-live")
    assert store.checkpoint_path.read_bytes() == before
    assert not (store.run_dir / "report.md").exists()
    assert fake_llm.calls == []


# ── CLI and service reconcile their own run dirs ─────────────────────────────

def test_cli_status_reconciles_an_orphan_and_prints_terminal(wired, capsys):
    from research_agent.__main__ import main

    store = ArtifactStore(wired / "cli-orphan")
    store.save_checkpoint(Checkpoint(run_id="cli-orphan", runbook="mini-teardown"))
    assert main(["status", "cli-orphan"]) == 0
    out = capsys.readouterr().out
    assert "interrupted" in out and "terminal: interrupted" in out


def test_cli_has_no_checkpoint_writer_of_its_own():
    import research_agent.__main__ as cli

    assert not hasattr(cli, "_mark_run_failed")


def test_service_recover_reconciles_its_run_dirs(tmp_path):
    from research_agent.service.store import Store

    orphan = ArtifactStore(tmp_path / "runs" / "pr-orphan")
    orphan.save_checkpoint(Checkpoint(run_id="pr-orphan", runbook="mini-teardown"))
    active = ArtifactStore(tmp_path / "runs" / "pr-active")
    active.save_checkpoint(Checkpoint(run_id="pr-active", runbook="mini-teardown"))
    before = active.checkpoint_path.read_bytes()
    store = Store(tmp_path)
    try:
        with hold_run_lock(active.run_dir):
            store.recover()
    finally:
        store.db.close()
    assert orphan.load_checkpoint().terminal_code == "interrupted"
    assert active.checkpoint_path.read_bytes() == before


async def test_service_cancel_reaches_the_orchestrator(tmp_path, monkeypatch, patched_runbooks):
    import research_agent.service.runtime as runtime_mod
    from research_agent.service.runtime import Runtime
    from research_agent.service.store import Store

    monkeypatch.setenv("PROWL_API_KEY", "test-not-a-key")
    monkeypatch.setenv("RESEARCH_LLM_API_KEY", "test-not-a-key")
    monkeypatch.setenv("RESEARCH_NO_SUBAGENTS", "1")
    prowl = BlockingProwl()
    llm = FakeLLM()
    llm.plan_payload = steps()

    class FakeObservedProwl:
        def __init__(self, *args, **kwargs):
            pass

        def observe(self, store, job):
            return prowl

    class FakeObservedLLM:
        def __init__(self, *args, **kwargs):
            pass

        def observe(self, store, job):
            return llm

    monkeypatch.setattr(runtime_mod, "ObservedProwl", FakeObservedProwl)
    monkeypatch.setattr(runtime_mod, "ObservedLLM", FakeObservedLLM)
    store = Store(tmp_path)
    rt = Runtime(store)
    try:
        job = rt.create({"kind": "research", "runbook": "mini-teardown", "inputs": BRIEF}, "cancel-live")
        rt.decide(job["id"], job["proposal"]["digest"], True)
        await asyncio.wait_for(prowl.entered.wait(), timeout=10)
        rt.cancel(job["id"])
        await asyncio.gather(*list(rt.tasks.values()), return_exceptions=True)
        checkpoint = ArtifactStore(tmp_path / "runs" / job["id"]).load_checkpoint()
        assert checkpoint.status == "partial"
        assert checkpoint.terminal_code == "cancelled"
        assert store.job(job["id"])["status"] == "cancelled"
    finally:
        await rt.close()
        store.db.close()


# ── events.py ────────────────────────────────────────────────────────────────

def test_emit_formats_one_line(caplog):
    from research_agent.events import emit

    logger = logging.getLogger("research_agent.test_events")
    with caplog.at_level(logging.INFO, logger="research_agent.test_events"):
        line = emit(logger, "run.terminal", run_id="r1", status="partial",
                    terminal_code="cancelled", partial=True, calls=3, cost=0.5, note=None,
                    reason="two words")
    assert line == (
        "event=run.terminal run_id=r1 status=partial terminal_code=cancelled "
        "partial=True calls=3 cost=0.5 note=None reason='two words'"
    )
    assert caplog.records[-1].getMessage() == line
    assert caplog.records[-1].levelno == logging.INFO


def test_emit_truncates_long_strings():
    from research_agent.events import emit

    line = emit(logging.getLogger("research_agent.test_events"), "x", reason="a" * 500)
    value = line.split("reason=", 1)[1]
    assert value == "a" * 200


def test_emit_refuses_secret_keys_in_strict_mode():
    from research_agent.events import emit

    logger = logging.getLogger("research_agent.test_events")
    for key in ("api_key", "token", "client_secret", "Authorization", "password", "cookie"):
        with pytest.raises(ValueError, match="credential"):
            emit(logger, "x", **{key: "value"})


def test_emit_drops_secret_keys_with_a_warning_outside_strict(monkeypatch, caplog):
    from research_agent.events import emit

    monkeypatch.delenv("RESEARCH_EVENTS_STRICT", raising=False)
    logger = logging.getLogger("research_agent.test_events")
    with caplog.at_level(logging.INFO, logger="research_agent.test_events"):
        line = emit(logger, "x", run_id="r1", api_key="sk-should-not-appear")
    assert line == "event=x run_id=r1"
    assert "sk-should-not-appear" not in caplog.text
    assert any(r.levelno == logging.WARNING and "api_key" in r.getMessage() for r in caplog.records)


async def test_service_cancel_after_the_run_finished_writes_nothing(tmp_path, monkeypatch, patched_runbooks):
    import research_agent.service.runtime as runtime_mod
    from research_agent.service.runtime import Runtime
    from research_agent.service.store import Store

    monkeypatch.setenv("PROWL_API_KEY", "test-not-a-key")
    monkeypatch.setenv("RESEARCH_LLM_API_KEY", "test-not-a-key")
    monkeypatch.setenv("RESEARCH_NO_SUBAGENTS", "1")
    prowl, llm = FakeProwl(), FakeLLM()
    llm.plan_payload = steps()

    class Observed:
        def __init__(self, client):
            self.client = client

        def __call__(self, *args, **kwargs):
            return self

        def observe(self, store, job):
            return self.client

    monkeypatch.setattr(runtime_mod, "ObservedProwl", Observed(prowl))
    monkeypatch.setattr(runtime_mod, "ObservedLLM", Observed(llm))
    store = Store(tmp_path)
    rt = Runtime(store)
    try:
        job = rt.create({"kind": "research", "runbook": "mini-teardown", "inputs": BRIEF}, "done-then-cancel")
        rt.decide(job["id"], job["proposal"]["digest"], True)
        await asyncio.gather(*list(rt.tasks.values()))
        assert store.job(job["id"])["status"] == "completed"
        checkpoint_path = tmp_path / "runs" / job["id"] / "checkpoint.json"
        before = checkpoint_path.read_bytes()
        assert json.loads(before)["terminal_code"] == "completed"
        assert store.job(job["id"])["result"]["output"]["research"]["terminal_code"] == "completed"
        rt.cancel(job["id"])
        assert store.job(job["id"])["status"] == "completed"
        assert checkpoint_path.read_bytes() == before
    finally:
        await rt.close()
        store.db.close()


def test_runlock_api(tmp_path):
    from research_agent.evidence.runlock import RunLock, RunLocked, is_locked_elsewhere

    run_dir = tmp_path / "r"
    assert not is_locked_elsewhere(run_dir)
    assert not run_dir.exists()  # a probe never creates the run dir or its lock
    with RunLock(run_dir) as owner:
        assert owner.held
        assert is_locked_elsewhere(run_dir)
        other = RunLock(run_dir)
        assert other.acquire(blocking=False) is False
        with pytest.raises(RunLocked, match="locked by another process"):
            with RunLock(run_dir):
                pass
    assert not is_locked_elsewhere(run_dir)
    again = RunLock(run_dir)
    assert again.acquire() is True
    again.release()
    again.release()  # idempotent


# ── Wave-1 fix round (W1-F1): seam/product certification findings ───────────

async def test_research_run_wait_false_refuses_a_run_locked_elsewhere(wired):
    store = ArtifactStore(wired / "live-elsewhere")
    store.save_checkpoint(Checkpoint(run_id="live-elsewhere", runbook="mini-teardown"))
    before = store.checkpoint_path.read_bytes()
    with hold_run_lock(store.run_dir):
        with pytest.raises(OrchestratorError, match="locked by another process"):
            await srv.research_run("mini-teardown", BRIEF, "live-elsewhere", wait=False)
        assert "live-elsewhere" not in srv._TASKS
        status = srv._status_dict("live-elsewhere")
    assert status["orphaned"] is False
    assert status["active"] is True
    assert store.checkpoint_path.read_bytes() == before


def test_status_reports_a_true_orphan_as_orphaned_and_inactive(wired):
    store = ArtifactStore(wired / "dead")
    store.save_checkpoint(Checkpoint(run_id="dead", runbook="mini-teardown"))
    status = srv._status_dict("dead")
    assert status["orphaned"] is True
    assert status["active"] is False


async def test_wait_true_envelope_validates_against_the_published_schema(wired, monkeypatch):
    import jsonschema
    from pathlib import Path

    schema = json.loads(
        (Path(__file__).resolve().parent.parent / "fabric/schemas/capability-output.schema.json").read_text()
    )
    llm = FakeLLM()
    llm.plan_payload = steps(1)
    monkeypatch.setattr(srv, "_make_llm", lambda config: llm)
    envelope = await srv.research_run("mini-teardown", BRIEF, "schema-env", wait=True)
    errors = [e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(envelope)]
    assert errors == []
    assert envelope["terminal_code"] == "completed"


def test_reconcile_survives_an_unwritable_run_dir(wired):
    import os
    from research_agent.evidence.runlock import reconcile_orphans

    stuck = ArtifactStore(wired / "a-stuck")
    stuck.save_checkpoint(Checkpoint(run_id="a-stuck", runbook="mini-teardown"))
    orphan = ArtifactStore(wired / "b-orphan")
    orphan.save_checkpoint(Checkpoint(run_id="b-orphan", runbook="mini-teardown"))
    os.chmod(stuck.run_dir, 0o500)
    try:
        marked = reconcile_orphans(wired)
    finally:
        os.chmod(stuck.run_dir, 0o755)
    assert "b-orphan" in marked
    assert orphan.load_checkpoint().status == "interrupted"


def test_emit_allows_ordinary_names_that_contain_credential_words(caplog):
    from research_agent.events import emit

    with caplog.at_level(logging.INFO):
        line = emit(logging.getLogger("t"), "x", keyword="a", keywords="b", input_tokens=3,
                    output_tokens=4, tokens_in=1, tokens_out=2)
    for field in ("keyword=a", "keywords=b", "input_tokens=3", "output_tokens=4", "tokens_in=1", "tokens_out=2"):
        assert field in line
    for bad in ("api_key", "key", "token", "access_token", "secret", "authorization", "password", "cookie"):
        with pytest.raises(ValueError):
            emit(logging.getLogger("t"), "x", **{bad: "v"})


def test_emit_redacts_credentials_inside_error_values():
    from research_agent.events import emit

    line = emit(logging.getLogger("t"), "x",
                error="401 Bearer abc.def from sk-or-v1-123456 and prowl_ABCDEF123")
    assert "abc.def" not in line and "sk-or-v1-123456" not in line and "prowl_ABCDEF123" not in line
    assert line.count("[redacted]") == 3


async def test_usd_budget_stop_maps_to_budget_usd_end_to_end(wired):
    prowl = FakeProwl()
    prowl.cost_per_call = 0.30  # mini-usd allows $0.50
    llm = FakeLLM()
    llm.plan_payload = steps(4)
    result = await Orchestrator(prowl, llm, runs_root=wired).run("mini-usd", BRIEF, run_id="usd")
    assert result.status == "partial"
    assert result.terminal_code == "budget_usd"


async def test_minutes_budget_stop_maps_to_budget_minutes_end_to_end(wired, monkeypatch):
    import research_agent.agent.orchestrator as orch_mod
    from datetime import datetime as real_dt, timedelta, timezone

    class Later(real_dt):
        @classmethod
        def now(cls, tz=None):
            return real_dt.now(tz) + timedelta(minutes=31)

    llm = FakeLLM()
    llm.plan_payload = steps(2)
    orchestrator = Orchestrator(FakeProwl(), llm, runs_root=wired)
    real_plan = orchestrator._plan

    async def plan_then_age(*args, **kwargs):
        out = await real_plan(*args, **kwargs)
        monkeypatch.setattr(orch_mod, "datetime", Later)
        return out

    monkeypatch.setattr(orchestrator, "_plan", plan_then_age)
    result = await orchestrator.run("mini-teardown", BRIEF, run_id="minutes")
    assert result.terminal_code == "budget_minutes"


def test_budget_stop_texts_share_one_vocabulary():
    from research_agent.evidence import terminal

    for code in (terminal.BUDGET_TOOLS, terminal.BUDGET_USD, terminal.BUDGET_MINUTES):
        assert terminal.code_for_stop_reason(terminal.budget_stop_text(code, 1)) == code
    assert terminal.code_for_stop_reason(
        terminal.budget_stop_text(terminal.BUDGET_USD, 0.5, note="estimated from catalog prices")
    ) == terminal.BUDGET_USD


def test_cli_commands_share_one_runs_root(wired, capsys, monkeypatch, tmp_path):
    from research_agent.__main__ import main

    elsewhere = tmp_path / "cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # ./runs would be cwd/runs, RESEARCH_RUNS_DIR is wired
    store = ArtifactStore(wired / "rooted")
    store.save_checkpoint(Checkpoint(run_id="rooted", runbook="mini-teardown", status="complete"))
    (store.run_dir / "report.md").write_text("# R\n", encoding="utf-8")
    assert main(["report", "rooted"]) == 0
    assert not (elsewhere / "runs").exists()


def test_prune_deletes_through_a_tombstone_and_skips_os_errors(wired, capsys, monkeypatch):
    import os
    import shutil
    from datetime import datetime, timedelta, timezone
    from research_agent.__main__ import main

    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    for rid in ("old-a", "old-b"):
        s = ArtifactStore(wired / rid)
        s.save_checkpoint(Checkpoint(run_id=rid, runbook="mini-teardown", status="complete", created_at=old))
        cp = s.load_checkpoint(); cp.created_at = old
        s.checkpoint_path.write_text(cp.model_dump_json(), encoding="utf-8")
    real_rmtree = shutil.rmtree
    seen = []

    def rmtree(path, *a, **k):
        seen.append(os.path.basename(str(path)))
        if "old-b" in str(path):
            raise OSError("synthetic busy")
        return real_rmtree(path, *a, **k)

    monkeypatch.setattr(shutil, "rmtree", rmtree)
    assert main(["prune", "--older-than", "30d", "--yes"]) == 0
    out = capsys.readouterr().out
    assert all(name.startswith(".pruning-") for name in seen)
    assert not (wired / "old-a").exists()
    assert "skip" in out and "old-b" in out


def _service_with_blocking_prowl(tmp_path, monkeypatch):
    import research_agent.service.runtime as runtime_mod
    from research_agent.service.runtime import Runtime
    from research_agent.service.store import Store

    monkeypatch.setenv("PROWL_API_KEY", "test-not-a-key")
    monkeypatch.setenv("RESEARCH_LLM_API_KEY", "test-not-a-key")
    monkeypatch.setenv("RESEARCH_NO_SUBAGENTS", "1")
    prowl = BlockingProwl()
    llm = FakeLLM()
    llm.plan_payload = steps()

    class FakeObservedProwl:
        def __init__(self, *a, **k): pass
        def observe(self, store, job): return prowl

    class FakeObservedLLM:
        def __init__(self, *a, **k): pass
        def observe(self, store, job): return llm

    monkeypatch.setattr(runtime_mod, "ObservedProwl", FakeObservedProwl)
    monkeypatch.setattr(runtime_mod, "ObservedLLM", FakeObservedLLM)
    store = Store(tmp_path)
    return store, Runtime(store), prowl


async def test_service_timeout_has_its_own_code_and_carries_terminal_code(tmp_path, monkeypatch, patched_runbooks):
    from research_agent.service.store import Store

    store, rt, prowl = _service_with_blocking_prowl(tmp_path, monkeypatch)
    real_job = Store.job

    def short_timeout(self, job_id):
        job = real_job(self, job_id)
        if job is not None and job.get("config"):
            job["config"] = {**job["config"], "timeout_minutes": 0.02}
        return job

    monkeypatch.setattr(Store, "job", short_timeout)
    try:
        job = rt.create({"kind": "research", "runbook": "mini-teardown", "inputs": BRIEF}, "timeout-live")
        rt.decide(job["id"], job["proposal"]["digest"], True)
        await asyncio.gather(*list(rt.tasks.values()), return_exceptions=True)
        record = store.job(job["id"])
        assert record["status"] == "failed"
        assert record["error"]["code"] == "timeout"
        assert record["error"]["terminalCode"] == "cancelled"
        assert ArtifactStore(tmp_path / "runs" / job["id"]).load_checkpoint().terminal_code == "cancelled"
    finally:
        await rt.close()
        store.db.close()


async def test_service_shutdown_marks_job_interrupted_and_checkpoint_cancelled(tmp_path, monkeypatch, patched_runbooks):
    store, rt, prowl = _service_with_blocking_prowl(tmp_path, monkeypatch)
    try:
        job = rt.create({"kind": "research", "runbook": "mini-teardown", "inputs": BRIEF}, "close-live")
        rt.decide(job["id"], job["proposal"]["digest"], True)
        await asyncio.wait_for(prowl.entered.wait(), timeout=10)
        await rt.close()
        record = store.job(job["id"])
        assert record["phase"] == "interrupted"
        assert record["error"]["terminalCode"] == "cancelled"
        assert ArtifactStore(tmp_path / "runs" / job["id"]).load_checkpoint().terminal_code == "cancelled"
    finally:
        store.db.close()


async def test_pre_checkpoint_status_cancelled_and_running_arms():
    async def forever():
        await asyncio.sleep(3600)

    running = asyncio.create_task(forever())
    await asyncio.sleep(0)
    live = srv._pre_checkpoint_status("starting", running)
    assert live["status"] == "running" and live["active"] is True and live["has_checkpoint"] is False
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    gone = srv._pre_checkpoint_status("starting", running)
    assert gone["status"] == "partial" and gone["terminal_code"] == "cancelled" and gone["active"] is False


def test_prune_refuses_at_delete_time_when_a_run_took_the_lock(wired, capsys, monkeypatch):
    from datetime import datetime, timedelta, timezone
    import research_agent.__main__ as cli

    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    s = ArtifactStore(wired / "late-start")
    cp = Checkpoint(run_id="late-start", runbook="mini-teardown", status="complete", created_at=old)
    s.save_checkpoint(cp)
    cp.created_at = old
    s.checkpoint_path.write_text(cp.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr("research_agent.evidence.runlock.is_locked_elsewhere", lambda run_dir: False)  # the scan saw it free
    with hold_run_lock(s.run_dir):
        assert cli.main(["prune", "--older-than", "30d", "--yes"]) == 0
    assert s.run_dir.exists()
    assert "lock held" in capsys.readouterr().out


def test_write_terminal_leaves_a_foreign_runbook_alone_and_never_raises(tmp_path, monkeypatch):
    store = ArtifactStore(tmp_path / "foreign")
    store.save_checkpoint(Checkpoint(run_id="foreign", runbook="other-runbook"))
    before = store.checkpoint_path.read_bytes()
    Orchestrator._write_terminal(store, "mini-teardown", status="failed", partial=None,
                                 stop_reason="boom", code="error")
    assert store.checkpoint_path.read_bytes() == before

    mine = ArtifactStore(tmp_path / "mine")
    mine.save_checkpoint(Checkpoint(run_id="mine", runbook="mini-teardown"))

    def broken(checkpoint):
        raise OSError("disk full")

    monkeypatch.setattr(mine, "save_checkpoint", broken)
    Orchestrator._write_terminal(mine, "mini-teardown", status="failed", partial=None,
                                 stop_reason="boom", code="error")  # must not raise
