"""Batch-R4 audit fixes: budget honesty, runs/ retention, Budget validation,
online validate_runbooks hardening, and the docs that describe them."""

from __future__ import annotations

import fcntl
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from research_agent.__main__ import _lock_held, main
from research_agent.evidence.store import ArtifactStore, Checkpoint
from research_agent.runbook import RunbookError, list_runbooks, load_runbook

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import validate_runbooks  # noqa: E402

from conftest import FakeLLM, FakeProwl  # noqa: E402


def _write_runbook(runbooks_dir: Path, budget: str) -> Path:
    runbook_dir = runbooks_dir / "bad-budget"
    runbook_dir.mkdir(parents=True)
    path = runbook_dir / "SKILL.md"
    path.write_text(
        f"""\
---
name: bad-budget
description: runbook with an invalid budget
version: "1.0"
tools: [spyfu_get_domain_stats]
budget: {{ {budget} }}
outputs: {{ report_template: test, formats: [markdown] }}
---

# Bad Budget
""",
        encoding="utf-8",
    )
    return path


class TestBudgetModelValidation:
    def test_zero_max_tool_calls_rejected(self, tmp_path: Path):
        path = _write_runbook(
            tmp_path, "max_tool_calls: 0, max_usd: 1.00, max_minutes: 10"
        )
        with pytest.raises(RunbookError, match="max_tool_calls"):
            load_runbook(path)

    def test_negative_max_tool_calls_rejected(self, tmp_path: Path):
        path = _write_runbook(
            tmp_path, "max_tool_calls: -5, max_usd: 1.00, max_minutes: 10"
        )
        with pytest.raises(RunbookError):
            load_runbook(path)

    def test_all_shipped_runbooks_have_positive_call_budget(self):
        runbooks = list_runbooks()
        assert len(runbooks) == 14
        for rb in runbooks:
            assert rb.meta.budget.max_tool_calls > 0, rb.name


class TestBudgetHonesty:
    def test_list_runbooks_marks_llm_separate(self, capsys):
        assert main(["list-runbooks"]) == 0
        out = capsys.readouterr().out
        assert "tool calls only" in out
        assert "LLM usage is metered separately" in out

    def test_run_stats_mark_budget_scope_and_llm_usage(
        self, patched_runbooks, tmp_path: Path
    ):
        from research_agent.agent.orchestrator import Orchestrator

        class UsageLLM(FakeLLM):
            def usage_snapshot(self):
                return {
                    "calls": 2,
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "by_tier": {},
                }

        llm = UsageLLM()
        llm.plan_payload = {
            "plan": [
                {"step": "s0", "tool": "spyfu_get_domain_stats", "arguments": {}}
            ]
        }
        orchestrator = Orchestrator(FakeProwl(), llm, runs_root=tmp_path / "runs")
        import asyncio

        result = asyncio.run(
            orchestrator.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r1")
        )
        assert "tool calls only" in result.stats["budget_scope"]
        assert result.stats["llm_usage"]["calls"] == 2


def _make_run(runs_root: Path, run_id: str, age_days: int, status: str) -> Path:
    store = ArtifactStore(runs_root / run_id)
    created = datetime.now(timezone.utc) - timedelta(days=age_days)
    store.save_checkpoint(
        Checkpoint(run_id=run_id, runbook="mini", status=status, created_at=created.isoformat())
    )
    return store.run_dir


class TestPrune:
    def test_dry_run_deletes_nothing(self, monkeypatch, capsys, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        old = _make_run(tmp_path / "runs", "old-run", 60, "complete")
        monkeypatch.setattr("sys.argv", ["prune"])
        assert main(["prune"]) == 0
        out = capsys.readouterr().out
        assert "would delete" in out and "old-run" in out
        assert old.is_dir()

    def test_yes_deletes_only_old_runs(self, monkeypatch, capsys, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        old = _make_run(tmp_path / "runs", "old-run", 60, "complete")
        young = _make_run(tmp_path / "runs", "young-run", 2, "complete")
        assert main(["prune", "--yes"]) == 0
        assert not old.exists()
        assert young.is_dir()
        assert "young-run" in capsys.readouterr().out

    def test_keep_last_protects_newest(self, monkeypatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        older = _make_run(tmp_path / "runs", "a-older", 90, "complete")
        newer = _make_run(tmp_path / "runs", "b-newer", 60, "complete")
        assert main(["prune", "--yes", "--keep-last", "1"]) == 0
        assert not older.exists()
        assert newer.is_dir()

    def test_locked_run_is_never_deleted(self, monkeypatch, capsys, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        locked = _make_run(tmp_path / "runs", "locked-run", 60, "running")
        lock_path = locked / ".lock"
        lock_path.write_text("", encoding="utf-8")
        with lock_path.open("r+b") as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert main(["prune", "--yes"]) == 0
            assert locked.is_dir()
            assert "lock held" in capsys.readouterr().out
            fcntl.flock(held.fileno(), fcntl.LOCK_UN)

    def test_stale_running_run_without_lock_is_prunable(
        self, monkeypatch, tmp_path: Path
    ):
        monkeypatch.chdir(tmp_path)
        stale = _make_run(tmp_path / "runs", "stale-run", 60, "interrupted")
        assert main(["prune", "--yes"]) == 0
        assert not stale.exists()

    def test_run_without_checkpoint_is_skipped(self, monkeypatch, capsys, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        stray = tmp_path / "runs" / "stray"
        stray.mkdir(parents=True)
        assert main(["prune", "--yes"]) == 0
        assert stray.is_dir()
        assert "no readable checkpoint" in capsys.readouterr().out

    def test_invalid_older_than_exits_2(self, monkeypatch, capsys, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        assert main(["prune", "--older-than", "soon"]) == 2
        assert "--older-than" in capsys.readouterr().err

    def test_no_runs_dir_is_a_noop(self, monkeypatch, capsys, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        assert main(["prune", "--yes"]) == 0
        assert "nothing to prune" in capsys.readouterr().out

    def test_lock_held_helper(self, tmp_path: Path):
        lock = tmp_path / ".lock"
        lock.write_text("", encoding="utf-8")
        assert _lock_held(lock) is False
        with lock.open("r+b") as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert _lock_held(lock) is True
            fcntl.flock(held.fileno(), fcntl.LOCK_UN)
        assert _lock_held(tmp_path / "missing.lock") is False


class TestOnlineValidation:
    def test_config_from_env_without_llm_key(self, monkeypatch):
        from research_agent.config import Config

        monkeypatch.setenv("PROWL_API_KEY", "prowl_test")
        monkeypatch.delenv("RESEARCH_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        config = Config.from_env(require_llm=False)
        assert config.prowl_api_key == "prowl_test"
        assert config.llm_api_key == ""

    def test_online_catalog_load_needs_no_llm_key(self, monkeypatch):
        import research_agent.prowl_client as prowl_module

        class FakeClient:
            def __init__(self, api_key: str, mcp_url: str) -> None:
                assert api_key == "prowl_test"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return None

            async def list_tools(self):
                return ["spyfu_get_domain_stats"]

        monkeypatch.setenv("PROWL_API_KEY", "prowl_test")
        monkeypatch.delenv("RESEARCH_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setattr(prowl_module, "ProwlClient", FakeClient)
        import asyncio

        assert asyncio.run(validate_runbooks._load_catalog(offline=False)) == [
            "spyfu_get_domain_stats"
        ]

    def test_network_error_is_clean_exit_2(self, monkeypatch, capsys):
        async def boom(offline: bool):
            raise OSError("connection refused")

        monkeypatch.setenv("PROWL_API_KEY", "prowl_test")
        monkeypatch.setattr(validate_runbooks, "_load_catalog", boom)
        assert validate_runbooks.main(["--online"]) == 2
        err = capsys.readouterr().err
        assert "could not load the live catalog" in err
        assert "Traceback" not in err

    def test_offline_still_passes(self, capsys):
        assert validate_runbooks.main(["--offline"]) == 0
        assert "all runbooks valid" in capsys.readouterr().out


class TestR4Docs:
    def test_readme_documents_prune(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "`prune [--older-than 30d] [--keep-last N]" in readme
        assert "--yes" in readme
        assert ".lock" in readme

    def test_readme_documents_validate_exit_codes(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "2 on" in readme and "network" in readme

    def test_readme_marks_llm_outside_budget(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "stats.llm_usage" in readme
        assert "Prowl tool calls only" in readme

    def test_authoring_guide_marks_llm_outside_budget(self):
        authoring = (REPO_ROOT / "docs" / "runbook-authoring.md").read_text(
            encoding="utf-8"
        )
        assert "stats.llm_usage" in authoring
