"""Real two-process smoke for run ownership (KA-06).

A helper subprocess holds a run's lock the way a live CLI run or another MCP
server would; this process then tries every non-owner path against the same
run dir. The CLI cannot run a research job offline (no fake-provider hook), so
the owner is a lock-holding helper rather than a second `python -m
research_agent run`.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import research_agent.mcp_server as srv
from research_agent.agent.orchestrator import OrchestratorError
from research_agent.config import Config
from research_agent.evidence.store import ArtifactStore, Checkpoint

from conftest import FakeLLM, FakeProwl

REPO = Path(__file__).resolve().parent.parent

HOLDER = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from research_agent.evidence.runlock import RunLock

    lock = RunLock(Path(sys.argv[1]))
    assert lock.acquire(blocking=False), "helper could not take the lock"
    print("locked", flush=True)
    sys.stdin.readline()  # hold until the test closes stdin
    lock.release()
    """
)


@pytest.fixture
def wired(monkeypatch, patched_runbooks, tmp_path):
    monkeypatch.setenv("RESEARCH_RUNS_DIR", str(tmp_path / "runs"))
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


async def test_second_process_cannot_write_a_locked_run(wired):
    store = ArtifactStore(wired / "two-proc")
    store.save_checkpoint(Checkpoint(run_id="two-proc", runbook="mini-teardown"))
    before = store.checkpoint_path.read_bytes()

    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(store.run_dir)],
        cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "locked"

        with pytest.raises(OrchestratorError, match="locked by another process"):
            await srv.research_run("mini-teardown", {"competitors": ["a.com"]}, "two-proc", wait=True)
        srv._reconcile_orphaned_runs()
        from research_agent.evidence.runlock import is_locked_elsewhere

        assert is_locked_elsewhere(store.run_dir)
        assert store.checkpoint_path.read_bytes() == before
    finally:
        assert holder.stdin is not None
        holder.stdin.close()
        holder.wait(timeout=10)

    # The owner is gone without a terminal write: now, and only now, the
    # checkpoint is a true orphan and reconciliation may claim it.
    srv._reconcile_orphaned_runs()
    assert store.load_checkpoint().terminal_code == "interrupted"
