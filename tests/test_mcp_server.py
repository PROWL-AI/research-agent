import json
import logging
from pathlib import Path

import pytest

import research_agent.mcp_server as srv
from research_agent.config import Config, ConfigError

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


async def test_list_runbooks_needs_no_keys(wired):
    runbooks = await srv.research_list_runbooks()
    names = [rb["name"] for rb in runbooks]
    assert "mini-teardown" in names
    entry = next(rb for rb in runbooks if rb["name"] == "mini-teardown")
    assert entry["budget"]["max_tool_calls"] == 2
    assert any(i["name"] == "competitors" for i in entry["inputs"])


async def test_list_runbooks_via_fastmcp_call_tool(wired):
    result = await srv.mcp.call_tool("research.list_runbooks", {})
    blocks, structured = result if isinstance(result, tuple) else (result, None)
    payload = structured["result"] if structured else json.loads(blocks[0].text)
    assert any(rb["name"] == "mini-teardown" for rb in payload)


async def test_run_rejects_unknown_runbook(wired):
    with pytest.raises(ValueError, match="unknown runbook"):
        await srv.research_run("nope", {"competitors": ["a.com"]})


async def test_run_rejects_missing_required_input(wired):
    with pytest.raises(ValueError, match="competitors"):
        await srv.research_run("mini-teardown", {})


async def test_run_fails_fast_naming_missing_key(wired, monkeypatch):
    def no_config():
        raise ConfigError("PROWL_API_KEY is not set — get a key at https://prowl.chat")

    monkeypatch.setattr(srv, "_config_from_env", no_config)
    with pytest.raises(ValueError, match="PROWL_API_KEY"):
        await srv.research_run("mini-teardown", {"competitors": ["a.com"]})


async def test_run_wait_true_returns_typed_envelope(wired, fake_llm, tmp_path):
    fake_llm.plan_payload = _one_step_plan()
    result = await srv.research_run(
        "mini-teardown", {"competitors": ["a.com"]}, run_id="mcp-wait", wait=True
    )
    assert result["run_id"] == "mcp-wait"
    assert result["status"] == "complete"
    assert Path(result["report_path"]).is_file()
    assert Path(result["ledger_path"]).is_file()
    assert result["stats"]["data_calls"] == 1
    assert result["skipped_steps"] == []


async def test_run_wait_false_job_handle_then_status_and_report(
    wired, fake_llm, tmp_path
):
    fake_llm.plan_payload = _one_step_plan()
    handle = await srv.research_run(
        "mini-teardown", {"competitors": ["a.com"]}, run_id="mcp-job"
    )
    assert handle == {"run_id": "mcp-job", "status": "running"}

    await srv._TASKS["mcp-job"]

    checkpoint = json.loads(
        (tmp_path / "runs" / "mcp-job" / "checkpoint.json").read_text()
    )
    assert checkpoint["status"] == "complete"
    assert (tmp_path / "runs" / "mcp-job" / "report.md").is_file()

    status = await srv.research_get_status("mcp-job")
    assert status["status"] == "complete"
    assert status["completed_steps"] == [0]
    assert status["counters"]["data_calls"] == 1
    assert status["duration_s"] is not None

    report = await srv.research_get_report("mcp-job")
    assert report["run_id"] == "mcp-job"
    assert report["report_markdown"] == fake_llm.report_text


async def test_get_status_unknown_run(wired):
    with pytest.raises(ValueError, match="unknown run_id"):
        await srv.research_get_status("no-such-run")


async def test_get_report_before_writer_fails_clearly(wired, tmp_path):
    from research_agent.evidence.store import ArtifactStore, Checkpoint

    store = ArtifactStore(tmp_path / "runs" / "mcp-early")
    store.save_checkpoint(Checkpoint(run_id="mcp-early", runbook="mini-teardown"))
    with pytest.raises(ValueError, match="no report yet"):
        await srv.research_get_report("mcp-early")


async def test_trace_id_reaches_run_log_lines(wired, fake_llm, caplog):
    fake_llm.plan_payload = _one_step_plan()
    with caplog.at_level(logging.INFO, logger="research_agent"):
        await srv.research_run(
            "mini-teardown", {"competitors": ["a.com"]},
            run_id="mcp-trace", wait=True, trace_id="t-123",
        )
    run_lines = [r for r in caplog.records if "mcp-trace" in r.getMessage()]
    assert run_lines
    assert all(getattr(r, "trace_id", None) == "t-123" for r in run_lines)


def test_cli_status_and_report_parity(wired, fake_llm, tmp_path, monkeypatch, capsys):
    from research_agent.__main__ import main
    from research_agent.evidence.store import ArtifactStore, Checkpoint

    store = ArtifactStore(tmp_path / "runs" / "cli-run")
    checkpoint = Checkpoint(run_id="cli-run", runbook="mini-teardown")
    checkpoint.counters["data_calls"] = 3
    store.save_checkpoint(checkpoint)
    (tmp_path / "runs" / "cli-run" / "report.md").write_text("# CLI report\n")

    assert main(["status", "cli-run"]) == 0
    out = capsys.readouterr().out
    assert "cli-run" in out and "running" in out

    monkeypatch.chdir(tmp_path)
    assert main(["report", "cli-run"]) == 0
    assert "# CLI report" in capsys.readouterr().out

    assert main(["status", "nope"]) == 1


def test_cli_mcp_invokes_serve(monkeypatch):
    called = []
    monkeypatch.setattr("research_agent.mcp_server.serve", lambda: called.append(True))
    from research_agent.__main__ import main

    assert main(["mcp"]) == 0
    assert called == [True]


class TestRunIdValidation:
    async def test_traversal_run_id_rejected(self, wired):
        with pytest.raises(ValueError, match="invalid run_id"):
            await srv.research_run("mini-teardown", {"competitors": ["a.com"]}, run_id="../evil")

    async def test_get_status_validates_run_id(self, wired):
        with pytest.raises(ValueError, match="invalid run_id"):
            await srv.research_get_status("../../etc")

    async def test_get_report_validates_run_id(self, wired):
        with pytest.raises(ValueError, match="invalid run_id"):
            await srv.research_get_report("a/b")


class TestJobLifecycle:
    async def test_run_exists_in_status_before_planning_finishes(self, wired, fake_llm):
        fake_llm.plan_payload = _one_step_plan()
        handle = await srv.research_run("mini-teardown", {"competitors": ["a.com"]}, run_id="early1")
        assert handle["status"] == "running"
        # give the background task a moment to write the stub checkpoint
        import asyncio as _asyncio
        await _asyncio.sleep(0.05)
        status = await srv.research_get_status("early1")
        assert status["run_id"] == "early1"
        await _asyncio.wait_for(srv._TASKS["early1"], timeout=30)

    async def test_duplicate_run_id_rejected_while_running(self, wired, fake_llm):
        import asyncio as _asyncio
        fake_llm.plan_payload = _one_step_plan()
        await srv.research_run("mini-teardown", {"competitors": ["a.com"]}, run_id="dup1")
        await _asyncio.sleep(0.01)
        if "dup1" in srv._TASKS and not srv._TASKS["dup1"].done():
            with pytest.raises(ValueError, match="already running"):
                await srv.research_run("mini-teardown", {"competitors": ["a.com"]}, run_id="dup1")
        await _asyncio.wait_for(srv._TASKS["dup1"], timeout=30)

    async def test_wait_run_returns_typed_envelope(self, wired, fake_llm):
        fake_llm.plan_payload = _one_step_plan()
        result = await srv.research_run(
            "mini-teardown", {"competitors": ["a.com"]}, run_id="wait1", wait=True
        )
        assert result["run_id"] == "wait1"
        assert result["status"] in ("complete", "partial")
        assert "stats" in result and "skipped_steps" in result
