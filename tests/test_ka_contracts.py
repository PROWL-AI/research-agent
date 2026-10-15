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


# ── Wave 2 (W2-T1): step identity, step states, durability, attempt ledger ───
# Ported from the deep-audit probes (KA-10/11/12) and the prowl-app resume
# probes (KA-03/04/05). Assertions on v1 `completed_steps` are translated to
# v2 step states with the same intent; each translation is named inline.

from research_agent.agent.orchestrator import PlanItem  # noqa: E402
from research_agent.agent.subagent import WorkerContext, run_worker  # noqa: E402
from research_agent.evidence.ledger import Ledger  # noqa: E402
from research_agent.evidence.store import StepRecord, make_step_id  # noqa: E402

from conftest import ScriptedClient  # noqa: E402


def _v1_run(run_dir, *, plan, completed, raw_for=None, skipped=None, counters=None, status="interrupted"):
    """A version-1 run directory as the old code left it."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "raw").mkdir(exist_ok=True)
    for i in (completed if raw_for is None else raw_for):
        (run_dir / "raw" / f"{i:02d}_{plan[i]['tool']}.json").write_text("{}")
    (run_dir / "checkpoint.json").write_text(json.dumps({
        "run_id": run_dir.name, "runbook": "mini-teardown", "status": status,
        "brief": {"competitors": ["a.com"]}, "plan": plan, "completed_steps": completed,
        "skipped_steps": skipped or [], "counters": counters or {"data_calls": len(completed)},
    }))


def _records(*tools):
    return [StepRecord(step_id=make_step_id(i, t, {}), raw_index=i, tool=t, step=f"s{i}")
            for i, t in enumerate(tools)]


async def test_ka03_catalog_change_does_not_skip_an_unexecuted_step(patched_runbooks, tmp_path):
    # Probe: completed_steps=[0] and the done tool left the catalog. Translation:
    # the v1 run has its step-0 raw (a legitimate v1 run), so it migrates.
    plan = [{"step": "done", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "a.com"}},
            {"step": "pending", "tool": "dataforseo_bl_summary", "arguments": {"target": "a.com"}}]
    _v1_run(tmp_path / "resume", plan=plan, completed=[0])
    prowl = FakeProwl(catalog=["dataforseo_bl_summary"])
    await Orchestrator(prowl, FakeLLM(), tmp_path).run("mini-teardown", {}, run_id="resume")
    assert [c["name"] for c in prowl.tool_calls] == ["dataforseo_bl_summary"]


async def test_ka03_v2_catalog_change_excludes_by_id_and_shifts_nothing(patched_runbooks, tmp_path):
    store = ArtifactStore(tmp_path / "v2")
    steps = _records("spyfu_get_domain_stats", "dataforseo_bl_summary", "spyfu_get_domain_stats")
    steps[2].arguments = {"domain": "c.com"}
    store.save_checkpoint(Checkpoint(run_id="v2", runbook="mini-teardown", status="interrupted",
                                     brief={"competitors": ["a.com"]}, steps=steps))
    prowl = FakeProwl(catalog=["dataforseo_bl_summary"])  # spyfu vanished
    result = await Orchestrator(prowl, FakeLLM(), tmp_path).run("mini-teardown", {}, run_id="v2")
    states = [s.state for s in store.load_checkpoint().steps]
    assert states == ["excluded", "completed", "excluded"]
    assert [c["name"] for c in prowl.tool_calls] == ["dataforseo_bl_summary"]
    assert result.status == "partial"  # a catalog change is a disclosed omission


async def test_ka04_unstarted_steps_after_failure_remain_resumable(tmp_path):
    # Probe: `1 not in completed_steps`. Translation: step 1 stays `pending`,
    # the failed step is `failed` (resumable), never `completed`.
    prowl = FakeProwl()
    prowl.fail_on.add("spyfu_get_domain_stats")
    steps = _records("spyfu_get_domain_stats", "dataforseo_bl_summary")
    checkpoint = Checkpoint(run_id="stopped", runbook="mini-teardown", steps=steps)
    orch = type("O", (), {"prowl": prowl, "_budget_stop_reason": staticmethod(lambda *_: None)})()
    ctx = WorkerContext(orch, checkpoint, ArtifactStore(tmp_path), Ledger(tmp_path / "ledger.json"), None)
    await run_worker(0, steps, ctx)
    assert [s.state for s in steps] == ["failed", "pending"]
    assert len(prowl.tool_calls) == 1


async def test_ka05_completed_step_is_persisted_before_worker_returns(tmp_path):
    # Probe: disk completed_steps == memory. Translation: the step's state on
    # disk is `completed` with its raw ref the moment the worker returns.
    prowl = FakeProwl()
    steps = _records("spyfu_get_domain_stats")
    checkpoint = Checkpoint(run_id="crash", runbook="mini-teardown", steps=steps)
    store = ArtifactStore(tmp_path)
    orch = type("O", (), {"prowl": prowl, "_budget_stop_reason": staticmethod(lambda *_: None)})()

    async def extract(*_):
        return 0

    ctx = WorkerContext(orch, checkpoint, store, Ledger(tmp_path / "ledger.json"), None, extract)
    await run_worker(0, steps, ctx)
    saved = store.load_checkpoint().steps[0]
    assert saved.state == steps[0].state == "completed"
    assert saved.raw_ref and store.resolve(saved.raw_ref).is_file()


@pytest.mark.parametrize("fault", ["raw_write", "extraction"])
async def test_ka10_evidence_failure_cannot_report_complete(wired, monkeypatch, fault):
    llm = FakeLLM()
    llm.plan_payload = steps()
    llm.claims_payload = {"claims": [{"claim": "Observed value 42", "value": 42, "unit": "items",
                                      "subject": "example.com metric"}]}
    orch = Orchestrator(FakeProwl(), llm, runs_root=wired)
    if fault == "raw_write":
        def fail_write(*args):
            raise OSError("synthetic raw artifact write failure")
        monkeypatch.setattr(ArtifactStore, "save_raw", fail_write)
    else:
        async def fail_extract(*args):
            raise RuntimeError("synthetic extractor failure")
        monkeypatch.setattr(orch, "_extract_claims", fail_extract)
    result = await orch.run("mini-teardown", BRIEF, run_id=fault)
    assert result.status == "partial"
    assert result.terminal_code == "evidence_incomplete"
    step = ArtifactStore(wired / fault).load_checkpoint().steps[0]
    assert step.state == ("failed" if fault == "raw_write" else "raw_saved")
    ledger = Ledger.load(wired / fault / "ledger.json")
    assert all(ArtifactStore(wired / fault).resolve(c.raw_ref).is_file() for c in ledger.claims)


async def test_ka10_resume_finishes_extraction_from_saved_raw_without_paying(wired, monkeypatch):
    llm = FakeLLM()
    llm.plan_payload = steps()
    llm.claims_payload = {"claims": [{"claim": "Observed value 42", "value": 42, "unit": "items",
                                      "subject": "example.com metric"}]}
    first = Orchestrator(FakeProwl(), llm, runs_root=wired)

    async def fail_extract(*args):
        raise RuntimeError("synthetic extractor failure")

    monkeypatch.setattr(first, "_extract_claims", fail_extract)
    await first.run("mini-teardown", BRIEF, run_id="refinish")
    prowl = FakeProwl()
    result = await Orchestrator(prowl, llm, runs_root=wired).run("mini-teardown", BRIEF, run_id="refinish")
    assert prowl.tool_calls == []  # the raw was paid for and saved
    assert result.status == "complete"
    assert len(Ledger.load(wired / "refinish" / "ledger.json").claims) == 1


async def test_ka11_known_cost_does_not_discard_previous_estimates(wired):
    client = ScriptedClient([
        {"rows": [{"value": 42}]},
        {"rows": [{"value": 42}], "billing": {"actual_cost_usd": 0.3}},
        {"rows": [{"value": 42}], "billing": {"actual_cost_usd": 0.1}},
    ])
    llm = FakeLLM()
    llm.plan_payload = steps(3)
    result = await Orchestrator(client, llm, runs_root=wired).run("mini-usd", BRIEF, run_id="mixed-cost")
    # Before call three: estimated first call .4 + known second .3 > budget .5.
    assert client.dispatched == 2
    assert result.stats["cost_source"] == "mixed"
    assert result.stats["spend_usd"] == pytest.approx(0.7)


async def test_ka12_billed_failure_cost_survives_resume(wired):
    client = ScriptedClient([{"success": False, "error_class": "upstream_error",
                              "billing": {"actual_cost_usd": 0.6}}])
    llm = FakeLLM()
    llm.plan_payload = steps()
    result = await Orchestrator(client, llm, runs_root=wired).run("mini-usd", BRIEF, run_id="billed-failure")
    assert result.status == "partial"
    assert result.stats["cost_usd"] == pytest.approx(0.6)
    fresh = ScriptedClient([{"rows": [], "billing": {"actual_cost_usd": 0.6}}])
    resumed = await Orchestrator(fresh, llm, runs_root=wired).run("mini-usd", BRIEF, run_id="billed-failure")
    assert fresh.dispatched == 0
    assert resumed.terminal_code == "budget_usd"


async def test_control_success_persists_evidence_with_a_portable_raw_ref(wired):
    llm = FakeLLM()
    llm.plan_payload = steps()
    llm.claims_payload = {"claims": [{"claim": "Observed value", "value": 42, "unit": "items"}]}
    result = await Orchestrator(FakeProwl(), llm, runs_root=wired).run("mini-teardown", BRIEF, run_id="control")
    ledger = Ledger.load(wired / "control" / "ledger.json")
    assert result.status == "complete" and len(ledger.claims) == 1
    assert ledger.claims[0].raw_ref.startswith("raw/")  # run-dir-relative (B-025)
    assert ArtifactStore(wired / "control").resolve(ledger.claims[0].raw_ref).is_file()


async def test_outcome_unknown_attempt_is_resent_with_the_same_key(wired):
    store = ArtifactStore(wired / "unknown")
    record = _records("spyfu_get_domain_stats")[0]
    record.state = "dispatching"  # the process died mid-call
    checkpoint = Checkpoint(run_id="unknown", runbook="mini-teardown", status="running",
                            brief={"competitors": ["a.com"]}, steps=[record])
    from research_agent.evidence.store import AttemptRecord

    key = f"unknown:{record.step_id}:1"
    checkpoint.attempts.append(AttemptRecord(attempt_id=f"{record.step_id}#1", step_id=record.step_id,
                                             attempt_no=1, idempotency_key=key, estimate_usd=0.1))
    store.save_checkpoint(checkpoint)
    prowl = FakeProwl()
    await Orchestrator(prowl, FakeLLM(), wired).run("mini-teardown", {}, run_id="unknown")
    assert [c["idempotency_key"] for c in prowl.tool_calls] == [key]


async def test_refused_attempt_retries_with_a_new_attempt_number(wired):
    prowl = FakeProwl()
    prowl.fail_on.add(TOOL)
    llm = FakeLLM()
    llm.plan_payload = steps()
    await Orchestrator(prowl, llm, runs_root=wired).run("mini-teardown", BRIEF, run_id="retry")
    prowl.fail_on.clear()
    await Orchestrator(prowl, llm, runs_root=wired).run("mini-teardown", BRIEF, run_id="retry")
    keys = [c["idempotency_key"] for c in prowl.tool_calls]
    assert [k.rsplit(":", 1)[1] for k in keys] == ["1", "2"]


def test_migration_refuses_a_plan_refiltered_by_a_resume(tmp_path):
    from research_agent.evidence.store import CheckpointMigrationError

    plan = [{"step": "a", "tool": "spyfu_get_domain_stats"}, {"step": "b", "tool": "dataforseo_bl_summary"}]
    _v1_run(tmp_path / "regrown", plan=plan, completed=[0], skipped=[
        {"index": 1, "step": "b", "tool": "dataforseo_bl_summary", "reason": "not in live catalog",
         "kind": "plan_drop"}])
    with pytest.raises(CheckpointMigrationError, match="re-filtered"):
        ArtifactStore(tmp_path / "regrown").load_checkpoint()


def test_migration_refuses_a_raw_artifact_of_another_tool(tmp_path):
    from research_agent.evidence.store import CheckpointMigrationError

    plan = [{"step": "a", "tool": "spyfu_get_domain_stats"}]
    _v1_run(tmp_path / "shifted", plan=plan, completed=[0], raw_for=[])
    (tmp_path / "shifted" / "raw" / "00_dataforseo_bl_summary.json").write_text("{}")
    with pytest.raises(CheckpointMigrationError, match="shifted"):
        ArtifactStore(tmp_path / "shifted").load_checkpoint()


def test_migration_refuses_a_completed_step_without_evidence(tmp_path):
    from research_agent.evidence.store import CheckpointMigrationError

    plan = [{"step": "a", "tool": "spyfu_get_domain_stats"}]
    _v1_run(tmp_path / "lost", plan=plan, completed=[0], raw_for=[])
    with pytest.raises(CheckpointMigrationError, match="evidence may have been lost"):
        ArtifactStore(tmp_path / "lost").load_checkpoint()


def test_migration_maps_budget_and_tail_skips_to_pending_and_keeps_cost(tmp_path):
    plan = [{"step": f"s{i}", "tool": "spyfu_get_domain_stats", "arguments": {"d": i}} for i in range(4)]
    plan[2]["on_error_skip"] = True
    _v1_run(tmp_path / "mapped", plan=plan, completed=[0, 1, 2, 3], raw_for=[0], skipped=[
        {"index": 1, "step": "s1", "tool": "t", "reason": "max_tool_calls=2", "kind": "runtime_skip"},
        {"index": 2, "step": "s2", "tool": "t", "reason": "upstream 500", "kind": "runtime_skip"},
        {"index": 3, "step": "s3", "tool": "t", "reason": "step 's0' failed: boom", "kind": "runtime_skip"},
    ], counters={"data_calls": 1, "attempted_calls": 3, "cost_usd": 0.45})
    checkpoint = ArtifactStore(tmp_path / "mapped").load_checkpoint()
    assert [s.state for s in checkpoint.steps] == ["completed", "pending", "skipped_on_error", "pending"]
    assert checkpoint.counters["attempted_calls"] == 3
    assert checkpoint.spend_usd("tool") == pytest.approx(0.45)
    assert checkpoint.migrated_from == 1


# ── Wave-2 fix round (W2-F1): certification findings on 0af84eb ──────────────

class _TimeoutOnceClient:
    """A real ProwlClient whose first dispatch times out the way the MCP SDK
    reports it (McpError 408); later dispatches answer."""

    def __new__(cls):
        from mcp.shared.exceptions import McpError
        from mcp.types import CallToolResult, ErrorData

        from research_agent.prowl_client import ProwlClient

        class _C(ProwlClient):
            def __init__(self):
                super().__init__(api_key="test", mcp_url="http://unused.invalid")
                self.keys, self.calls = [], 0
                self.tool_prices = {TOOL: 0.1}

            async def list_tools(self):
                return [TOOL, "dataforseo_bl_summary"]

            async def tool_info(self, name):
                return {"name": name}

            async def _rpc(self, name, arguments, retry=True):
                self.calls += 1
                self.keys.append(arguments["idempotency_key"])
                if self.calls == 1:
                    raise McpError(ErrorData(code=408, message="Timed out while waiting for response"))
                return CallToolResult(content=[], structuredContent={"rows": [{"value": 1}]})

        return _C()


async def test_read_timeout_is_outcome_unknown_and_resent_with_the_same_key(wired):
    client = _TimeoutOnceClient()
    llm = FakeLLM()
    llm.plan_payload = steps()
    first = await Orchestrator(client, llm, runs_root=wired).run("mini-teardown", BRIEF, run_id="timeout")
    step = ArtifactStore(wired / "timeout").load_checkpoint().steps[0]
    assert first.status == "partial" and step.state == "outcome_unknown"
    await Orchestrator(client, llm, runs_root=wired).run("mini-teardown", BRIEF, run_id="timeout")
    assert client.keys[0] == client.keys[1]  # the server can replay instead of billing twice


async def test_raw_saved_step_is_extracted_even_after_the_tool_budget_is_spent(wired, monkeypatch):
    llm = FakeLLM()
    llm.plan_payload = steps(3)  # mini-teardown allows 2 calls
    llm.claims_payload = {"claims": [{"claim": "v", "value": 1, "unit": "u", "subject": "s"}]}
    first = Orchestrator(FakeProwl(), llm, runs_root=wired)
    real = first._extract_claims
    calls = {"n": 0}

    async def fail_first(*args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("extractor down")
        return await real(*args)

    monkeypatch.setattr(first, "_extract_claims", fail_first)
    await first.run("mini-teardown", BRIEF, run_id="stranded")
    prowl = FakeProwl()
    await Orchestrator(prowl, llm, runs_root=wired).run("mini-teardown", BRIEF, run_id="stranded")
    states = [s.state for s in ArtifactStore(wired / "stranded").load_checkpoint().steps]
    assert prowl.tool_calls == [] and states[0] == "completed"


async def test_budget_stop_keeps_an_outcome_unknown_step_and_its_key(wired):
    from research_agent.evidence.store import AttemptRecord

    store = ArtifactStore(wired / "u")
    record = _records(TOOL)[0]
    record.state = "dispatching"
    key = f"u:{record.step_id}:1"
    old = "2020-01-01T00:00:00+00:00"  # max_minutes (30) long gone
    checkpoint = Checkpoint(run_id="u", runbook="mini-teardown", status="running", created_at=old,
                            brief={"competitors": ["a.com"]}, steps=[record],
                            attempts=[AttemptRecord(attempt_id="a1", step_id=record.step_id,
                                                    idempotency_key=key, estimate_usd=0.1)])
    store.save_checkpoint(checkpoint)
    prowl = FakeProwl()
    stopped = await Orchestrator(prowl, FakeLLM(), wired).run("mini-teardown", {}, run_id="u")
    assert stopped.terminal_code == "budget_minutes" and prowl.tool_calls == []
    assert store.load_checkpoint().steps[0].state == "outcome_unknown"
    fresh = store.load_checkpoint()
    fresh.created_at = datetime_now_iso()
    store.save_checkpoint(fresh)
    await Orchestrator(prowl, FakeLLM(), wired).run("mini-teardown", {}, run_id="u")
    assert [c["idempotency_key"] for c in prowl.tool_calls] == [key]


def datetime_now_iso():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


@pytest.mark.parametrize("optional", [True, False])
async def test_raw_write_failure_is_skipped_when_optional_and_refetched_when_required(wired, monkeypatch, optional):
    llm = FakeLLM()
    llm.plan_payload = {"plan": [{"step": "s", "tool": TOOL, "arguments": {"domain": "a.com"},
                                  "on_error_skip": optional}]}
    orch = Orchestrator(FakeProwl(), llm, runs_root=wired)
    with monkeypatch.context() as m:
        def fail_write(*args):
            raise OSError("disk full")
        m.setattr(ArtifactStore, "save_raw", fail_write)
        await orch.run("mini-teardown", BRIEF, run_id=f"rw-{optional}")
    step = ArtifactStore(wired / f"rw-{optional}").load_checkpoint().steps[0]
    assert step.state == ("skipped_on_error" if optional else "failed")
    prowl = FakeProwl()
    await Orchestrator(prowl, llm, runs_root=wired).run("mini-teardown", BRIEF, run_id=f"rw-{optional}")
    if optional:
        assert prowl.tool_calls == []  # an optional step is not paid for again
    else:
        assert [c["idempotency_key"].rsplit(":", 1)[1] for c in prowl.tool_calls] == ["2"]


def test_judge_reads_a_v1_run_through_the_migration(tmp_path, patched_runbooks):
    from evals import judge

    plan = [{"step": "a", "tool": TOOL, "arguments": {"d": 1}}]
    _v1_run(tmp_path / "v1judge", plan=plan, completed=[0], counters={"data_calls": 1, "attempted_calls": 1})
    (tmp_path / "v1judge" / "report.md").write_text("# R\n\nText.\n")
    Ledger(tmp_path / "v1judge" / "ledger.json").save()
    report, ledger, checkpoint, runbook = judge.load_run(tmp_path / "v1judge")
    assert judge.programmatic_signals(report, ledger, checkpoint, runbook)["budget"]["data_calls_used"] == 1


async def test_v1_crash_between_save_and_completion_is_finished_without_paying(patched_runbooks, tmp_path):
    plan = [{"step": "a", "tool": TOOL, "arguments": {"d": 0}},
            {"step": "b", "tool": "dataforseo_bl_summary", "arguments": {"d": 1}}]
    _v1_run(tmp_path / "v1crash", plan=plan, completed=[0], raw_for=[0, 1])
    ledger = Ledger(tmp_path / "v1crash" / "ledger.json")
    ledger.add(claim="b value", value=5, unit="u", subject="b", source_tool="dataforseo_bl_summary",
               raw_ref="runs/v1crash/raw/01_dataforseo_bl_summary.json")  # a v1 cwd-relative ref
    ledger.save()
    llm = FakeLLM()
    llm.claims_payload = {"claims": [{"claim": "b value", "value": 5, "unit": "u", "subject": "b"}]}
    prowl = FakeProwl()
    result = await Orchestrator(prowl, llm, tmp_path).run("mini-teardown", {}, run_id="v1crash")
    assert prowl.tool_calls == []
    assert result.status == "complete"
    claims = Ledger.load(tmp_path / "v1crash" / "ledger.json").claims
    assert [c.claim for c in claims].count("b value") == 1  # replaced, not duplicated


async def test_a_run_that_needs_attention_stays_readable_and_is_never_resumed(wired, capsys):
    from research_agent.__main__ import main

    plan = [{"step": "a", "tool": TOOL}]
    _v1_run(wired / "attn", plan=plan, completed=[0], raw_for=[], status="complete")
    (wired / "attn" / "report.md").write_text("# Finished report\n")
    before = (wired / "attn" / "checkpoint.json").read_bytes()
    status = await srv.research_get_status("attn")
    assert status["status"] == "needs_attention" and "evidence may have been lost" in status["stop_reason"]
    report = await srv.research_get_report("attn")
    assert report["report_markdown"].startswith("# Finished report")
    assert report["checkpoint_status"].startswith("needs_attention")
    with pytest.raises(ValueError, match="needs attention"):
        await srv.research_run("mini-teardown", BRIEF, "attn", wait=True)
    assert main(["export", "attn", "--format", "html"]) == 1
    assert "evidence may have been lost" in capsys.readouterr().err
    assert (wired / "attn" / "checkpoint.json").read_bytes() == before


def test_migration_accepts_planner_time_duplicates_and_refuses_two_tools_at_one_index(tmp_path):
    from research_agent.evidence.store import CheckpointMigrationError

    plan = [{"step": "a", "tool": TOOL}]
    _v1_run(tmp_path / "dup", plan=plan, completed=[0], skipped=[
        {"index": 1, "step": "a", "tool": TOOL, "reason": "duplicate step (same tool and arguments)",
         "kind": "plan_drop"}])
    assert ArtifactStore(tmp_path / "dup").load_checkpoint().steps[0].state == "completed"
    _v1_run(tmp_path / "two", plan=plan, completed=[0])
    (tmp_path / "two" / "raw" / "00_dataforseo_bl_summary.json").write_text("{}")
    with pytest.raises(CheckpointMigrationError):
        ArtifactStore(tmp_path / "two").load_checkpoint()


async def test_migrated_v1_failed_step_is_first_resent_under_its_v1_key(patched_runbooks, tmp_path):
    plan = [{"step": "a", "tool": TOOL, "arguments": {"d": 0}}]
    _v1_run(tmp_path / "legacy", plan=plan, completed=[], raw_for=[], skipped=[
        {"index": 0, "step": "a", "tool": TOOL, "reason": "step 'a' failed: timeout", "kind": "runtime_skip"}])
    prowl = FakeProwl()
    await Orchestrator(prowl, FakeLLM(), tmp_path).run("mini-teardown", {}, run_id="legacy")
    assert [c["idempotency_key"] for c in prowl.tool_calls] == [f"legacy:0:{TOOL}"]


async def test_local_pre_dispatch_refusal_is_definite_and_free():
    from research_agent.prowl_client import ToolCallError
    from research_agent.service.runtime import ObservedProwl

    class FullStore:
        def calls(self, job_id):
            return [object()] * 256

    prowl = ObservedProwl(api_key="t", mcp_url="http://unused.invalid").observe(FullStore(), {"id": "j"})
    with pytest.raises(ToolCallError) as caught:
        await prowl.call_tool(TOOL, {}, idempotency_key="k")
    assert caught.value.cost_usd == 0.0


def test_status_views_are_honest_while_a_run_is_live():
    record = _records(TOOL)[0]
    record.state = "dispatching"
    live = Checkpoint(run_id="x", runbook="mini-teardown", steps=[record])
    assert live.skipped_steps == []  # in flight is progress, not an omission
    with pytest.raises(TypeError):
        live.counters["data_calls"] = 1  # derived from the ledger; a write must not vanish


def test_migration_counts_v1_successes_not_attempts_and_refuses_future_schemas(tmp_path):
    plan = [{"step": "a", "tool": TOOL}]
    _v1_run(tmp_path / "counts", plan=plan, completed=[0],
            counters={"data_calls": 1, "attempted_calls": 3, "cost_usd": 0.3})
    checkpoint = ArtifactStore(tmp_path / "counts").load_checkpoint()
    assert checkpoint.counters["data_calls"] == 1 and checkpoint.counters["attempted_calls"] == 3
    ArtifactStore(tmp_path / "counts").save_checkpoint(checkpoint)
    assert (tmp_path / "counts" / "checkpoint.v1.json").is_file()  # rollback stays possible
    future = tmp_path / "future"
    future.mkdir()
    (future / "checkpoint.json").write_text(json.dumps({"run_id": "future", "runbook": "x", "schema_version": 9}))
    with pytest.raises(ValueError, match="newer than this build"):
        ArtifactStore(future).load_checkpoint()


async def test_writer_is_told_which_steps_are_missing(wired):
    llm = FakeLLM()
    llm.plan_payload = steps(3)  # 2 calls allowed: baseline-2 is budget-skipped
    await Orchestrator(FakeProwl(), llm, runs_root=wired).run("mini-teardown", BRIEF, run_id="told")
    writer_prompts = [c["messages"][0]["content"] for c in llm.calls if c["tier"] == "strong" and not c["json_mode"]]
    assert any("baseline-2" in p and "partial" in p.lower() for p in writer_prompts)


async def test_skipped_budget_steps_run_only_once_the_budget_allows(wired, patched_runbooks, monkeypatch):
    llm = FakeLLM()
    llm.plan_payload = steps(3)
    await Orchestrator(FakeProwl(), llm, runs_root=wired).run("mini-teardown", BRIEF, run_id="raise")
    same = FakeProwl()
    await Orchestrator(same, llm, runs_root=wired).run("mini-teardown", BRIEF, run_id="raise")
    assert same.tool_calls == []  # the budget is still spent: nothing runs
    from research_agent.runbook import get_runbook

    rb = get_runbook("mini-teardown")
    # Raise both: the two earlier calls had no price and were estimated at the
    # per-call share of max_usd (1.00 / 2), so they already spent the USD budget.
    monkeypatch.setattr(rb.meta.budget, "max_tool_calls", 5)
    monkeypatch.setattr(rb.meta.budget, "max_usd", 5.0)
    monkeypatch.setattr("research_agent.agent.orchestrator.get_runbook", lambda name: rb)
    raised = FakeProwl()
    result = await Orchestrator(raised, llm, runs_root=wired).run("mini-teardown", BRIEF, run_id="raise")
    assert [c["arguments"]["domain"] for c in raised.tool_calls] == ["sample-2.example.com"]
    assert result.status == "complete"


# ── Wave 3 (W3-T1): ledger v2 — evidence truth (KA-07, KA-08, KA-09, B-007) ──
# Ported from the deep-audit probes; the v1 `verbatim=True` extractor flag is
# kept in the KA-08 payload on purpose — it must no longer verify anything.

from research_agent.evidence.ledger import ClaimStatus  # noqa: E402


def test_ka07_valueless_claim_cannot_erase_numeric_conflict(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    common = {"subject": "example.com monthly traffic", "unit": "visits"}
    a = ledger.add(claim="Traffic is 100", value=100, source_tool="tool_a", **common)
    b = ledger.add(claim="Traffic is 200", value=200, source_tool="tool_b", **common)
    assert a.status == b.status == ClaimStatus.conflict  # negative control
    ledger.add(claim="Traffic exists", source_tool="tool_c", **common)
    assert a.status == b.status == ClaimStatus.conflict


async def test_ka08_fabricated_verbatim_is_not_verified(tmp_path):
    llm = FakeLLM()
    llm.claims_payload = {"claims": [{
        "claim": "Revenue is USD 999 billion", "subject": "example.com annual revenue",
        "value": 999, "unit": "billion USD", "verbatim": True,
        "quote": "Revenue is USD 999 billion", "source_url": "https://example.invalid/not-in-raw",
    }]}
    ledger = Ledger(tmp_path / "ledger.json")
    orch = Orchestrator(FakeProwl(), llm, runs_root=tmp_path)
    await orch._extract_claims(PlanItem(step="baseline", tool=TOOL, arguments={}), {"rows": []},
                               tmp_path / "raw.json", ledger)
    assert not any(c.status == ClaimStatus.verified for c in ledger.claims)
    assert ledger.claims[0].verification["detail"] == "quote not found in stored raw"


def test_ka09_same_document_is_not_two_independent_sources(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    common = dict(claim="Revenue is 100 USD", subject="example.com annual revenue", value=100,
                  unit="USD", source_url="https://example.com/annual-report")
    ledger.add(source_tool="web_search", **common)
    ledger.add(source_tool="page_scraper", **{**common, "source_url": "https://www.example.com/annual-report/?utm_source=x"})
    assert all(c.status != ClaimStatus.verified for c in ledger.claims)


def test_two_independent_publishers_corroborate(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    common = dict(claim="Revenue is 100 USD", subject="example.com annual revenue", value=100, unit="USD")
    ledger.add(source_tool="web_search", source_url="https://example.com/report", **common)
    ledger.add(source_tool="web_search", source_url="https://news.example.org/story", **common)
    assert {c.status for c in ledger.claims} == {ClaimStatus.verified}
    assert {c.verification["method"] for c in ledger.claims} == {"corroboration"}


def test_two_data_providers_without_urls_corroborate_but_one_provider_does_not(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    common = dict(claim="1200 visits", subject="a.com visits", value=1200, unit="visits")
    one = ledger.add(source_tool="spyfu_get_domain_stats", **common)
    same = ledger.add(source_tool="spyfu_get_seo_keywords", **common)
    assert one.status == same.status == ClaimStatus.assumed  # one provider, two endpoints
    ledger.add(source_tool="dataforseo_labs_domain_rank", **common)
    assert {c.status for c in ledger.claims} == {ClaimStatus.verified}


def test_transform_claim_never_corroborates_its_source(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    common = dict(claim="1200 visits", subject="a.com visits", value=1200, unit="visits")
    ledger.add(source_tool="spyfu_get_domain_stats", **common)
    ledger.add(source_tool="transform", **common)  # an LLM summary of the line above (B-007)
    assert {c.status for c in ledger.claims} == {ClaimStatus.assumed}


def test_statuses_do_not_depend_on_insertion_order(tmp_path):
    import itertools

    rows = [
        dict(claim="100", value=100, source_tool="spyfu_a"),
        dict(claim="200", value=200, source_tool="dataforseo_b"),
        dict(claim="exists", value=None, source_tool="moz_c"),
        dict(claim="100 again", value=100, source_tool="web_search", source_url="https://x.com/a"),
        dict(claim="100 same doc", value=100, source_tool="page_scraper", source_url="https://x.com/a"),
    ]
    outcomes = set()
    for order in itertools.permutations(rows):
        ledger = Ledger(tmp_path / "l.json")
        for row in order:
            ledger.add(subject="s", unit="u", **row)
        outcomes.add(tuple(sorted((c.claim, c.status.value) for c in ledger.claims)))
    assert len(outcomes) == 1


def test_recompute_survives_save_and_load(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.add(claim="100", value=100, unit="u", subject="s", source_tool="spyfu_a")
    ledger.add(claim="200", value=200, unit="u", subject="s", source_tool="dataforseo_b")
    ledger.save()
    again = Ledger.load(tmp_path / "ledger.json")
    assert [c.status for c in again.claims] == [c.status for c in ledger.claims] == [ClaimStatus.conflict] * 2


def test_v1_verbatim_claim_without_a_quote_is_downgraded_on_load(tmp_path):
    (tmp_path / "ledger.json").write_text(json.dumps({"schema_version": 1, "claims": [{
        "id": "C1", "claim": "We grew 3x", "source_tool": "web_search", "verbatim": True, "status": "verified"}]}))
    claim = Ledger.load(tmp_path / "ledger.json").claims[0]
    assert claim.status == ClaimStatus.assumed
    assert claim.verification["detail"] == "v1 verbatim without quote"


@pytest.mark.parametrize("quote,value,expected", [
    ("Monthly visits reached 1,200 in May", 1200, "verified"),   # beyond 12k chars, below
    ("Monthly visits reached 1,200 in May", 999, "assumed"),     # value not inside the quote
    ("Nothing like this is in the raw", 1200, "assumed"),        # quote not in raw
])
async def test_span_verification_reads_the_whole_stored_raw(tmp_path, quote, value, expected):
    llm = FakeLLM()
    llm.claims_payload = {"claims": [{"claim": "visits", "subject": "a.com visits", "value": value,
                                      "unit": "visits", "quote": quote}]}
    raw = {"filler": "x " * 9000, "rows": [{"note": "Monthly visits   reached 1,200\nin May"}]}
    ledger = Ledger(tmp_path / "ledger.json")
    await Orchestrator(FakeProwl(), llm, runs_root=tmp_path)._extract_claims(
        PlanItem(step="s", tool=TOOL), raw, tmp_path / "raw.json", ledger)
    assert ledger.claims[0].status.value == expected
    if expected == "verified":
        assert ledger.claims[0].verification["method"] == "span" and ledger.claims[0].quote_span


def test_url_normalization_and_publisher():
    from research_agent.evidence.source import independence_key, normalize_url, publisher

    assert normalize_url("HTTPS://www.Example.com:443/a/?utm_source=x&b=1#frag") == "https://example.com/a?b=1"
    assert publisher("https://news.bbc.co.uk/x") == "bbc.co.uk"
    assert publisher("https://a.b.example.com/") == "example.com"
    assert independence_key("web_search", "https://www.example.com/a") == independence_key("page_scraper", "https://example.com/b")
    assert independence_key("transform", None) is None
    assert independence_key("spyfu_get_domain_stats", None) == "provider:spyfu"
