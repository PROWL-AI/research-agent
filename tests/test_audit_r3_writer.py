"""Regression tests for audit round 3, batch R2: writer draft truncation,
billed-but-failed LLM usage accounting, judge failure signalling, rewrite
HTML refresh, retry-loop hygiene, and CLI exit-code honesty."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals"))

import judge

from research_agent.config import Config
from research_agent.evidence.ledger import Ledger
from research_agent.evidence.store import ArtifactStore, Checkpoint
from research_agent.llm import LLMClient, LLMError


def _one_claim_ledger(tmp_path: Path) -> Ledger:
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.add(
        claim="a.com traffic is 150,000",
        subject="a.com monthly organic traffic",
        value=150000,
        unit="visits/month",
        source_tool="spyfu_get_domain_stats",
    )
    return ledger


class _TextLLM:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict] = []

    async def complete(self, messages, tier="cheap", json_mode=False, **kwargs):
        self.calls.append({"tier": tier, "json_mode": json_mode, **kwargs})
        return self.text


class _QueueLLM:
    """Serves queued str/LLMError responses; records max_tokens per call."""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.max_tokens_seen: list[int | None] = []

    async def complete(self, messages, tier="cheap", json_mode=False, **kwargs):
        self.max_tokens_seen.append(kwargs.get("max_tokens"))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _ok_payload(content="ok", finish="stop", prompt=10, completion=5):
    return {
        "choices": [{"finish_reason": finish, "message": {"content": content}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }


class _StubProwl:
    """ProwlClient connects eagerly in __aenter__ — CLI tests never reach the
    network, so a no-op async-context stub stands in."""

    def __init__(self, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_StubProwl":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _client_with_post(monkeypatch, responses):
    client = LLMClient(
        base_url="http://unused.invalid", api_key="k",
        model_cheap="cheap-m", model_strong="strong-m",
    )
    calls: list[dict] = []
    queue = list(responses)

    async def fake_post(url, **kwargs):
        calls.append(kwargs)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(client._client, "post", fake_post)
    return client, calls


class TestWriterDraftTruncation:
    # R2.1: finish_reason='length' on the initial draft used to kill the whole
    # run after all the tool spend. Now: one retry with escalated max_tokens.

    async def test_length_truncated_draft_retries_with_escalated_max_tokens(
        self, patched_runbooks, tmp_path
    ):
        from research_agent.agent import writer
        from research_agent.runbook import get_runbook

        llm = _QueueLLM([
            LLMError(
                "LLM output truncated at max_tokens (finish_reason='length')",
                retryable=False, finish_reason="length", content="half a draft",
            ),
            "# Clean report\n\nNo numbers here.",
        ])
        draft = await writer.write_report(
            llm, get_runbook("mini-teardown"), _one_claim_ledger(tmp_path),
            {"competitors": ["a.com"]},
        )
        assert draft == "# Clean report\n\nNo numbers here."
        assert llm.max_tokens_seen == [
            writer._DRAFT_MAX_TOKENS, writer._DRAFT_ESCALATED_MAX_TOKENS,
        ]

    async def test_escalated_draft_still_truncated_ships_partial_draft(
        self, patched_runbooks, tmp_path
    ):
        from research_agent.agent import writer
        from research_agent.runbook import get_runbook

        llm = _QueueLLM([
            LLMError("cut", retryable=False, finish_reason="length", content="first half"),
            LLMError("cut", retryable=False, finish_reason="length", content="second half"),
        ])
        draft = await writer.write_report(
            llm, get_runbook("mini-teardown"), _one_claim_ledger(tmp_path),
            {"competitors": ["a.com"]},
        )
        assert "second half" in draft
        assert "truncated" in draft
        assert llm.max_tokens_seen == [
            writer._DRAFT_MAX_TOKENS, writer._DRAFT_ESCALATED_MAX_TOKENS,
        ]

    async def test_non_length_error_still_propagates(self, patched_runbooks, tmp_path):
        from research_agent.agent import writer
        from research_agent.runbook import get_runbook

        llm = _QueueLLM([LLMError("provider blew up", retryable=False)])
        with pytest.raises(LLMError, match="provider blew up"):
            await writer.write_report(
                llm, get_runbook("mini-teardown"), _one_claim_ledger(tmp_path),
                {"competitors": ["a.com"]},
            )


class TestBilledUsageAccounting:
    # R2.2: a length-truncated completion is billed in full by the provider —
    # it must land in usage even though _extract rejects the content.

    async def test_length_truncated_completion_records_usage(self, monkeypatch):
        payload = _ok_payload(content="cut off", finish="length", prompt=100, completion=8000)
        client, _ = _client_with_post(monkeypatch, [httpx.Response(200, json=payload)])
        with pytest.raises(LLMError, match="truncated"):
            await client.complete(
                [{"role": "user", "content": "hi"}], tier="strong", max_tokens=8000
            )
        snap = client.usage_snapshot()
        assert snap["calls"] == 1
        assert snap["prompt_tokens"] == 100
        assert snap["completion_tokens"] == 8000
        assert snap["by_tier"]["strong"]["completion_tokens"] == 8000
        await client.aclose()

    async def test_successful_completion_still_records_usage(self, monkeypatch):
        client, _ = _client_with_post(
            monkeypatch, [httpx.Response(200, json=_ok_payload(prompt=7, completion=3))]
        )
        result = await client.complete([{"role": "user", "content": "hi"}], tier="cheap")
        assert result == "ok"
        snap = client.usage_snapshot()
        assert snap["calls"] == 1
        assert snap["prompt_tokens"] == 7
        assert snap["by_tier"]["cheap"]["model"] == "cheap-m"
        await client.aclose()


class TestJudgeFailureSignalling:
    # R2.3: an unparseable judge reply used to become a silent 0.00 FAIL,
    # indistinguishable from an honestly bad report; '{garbage' crashed with
    # an uncaught JSONDecodeError. Both are now JudgeError (exit 2).

    def _make_run(self, tmp_path: Path, run_id: str) -> Path:
        run_dir = tmp_path / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "report.md").write_text(
            "# Report\n\nTraffic is 150,000 visitors [C1].\n", encoding="utf-8"
        )
        ledger = Ledger(run_dir / "ledger.json")
        ledger.add(
            claim="a.com traffic is 150,000", subject="a.com traffic",
            value=150000, unit="visits/month", source_tool="spyfu_get_domain_stats",
        )
        ledger.save()
        checkpoint = Checkpoint(run_id=run_id, runbook="mini-teardown")
        (run_dir / "checkpoint.json").write_text(checkpoint.model_dump_json())
        return run_dir

    async def test_non_json_reply_raises_judge_error(self, patched_runbooks, tmp_path):
        run_dir = self._make_run(tmp_path, "r3-j1")
        with pytest.raises(judge.JudgeError, match="no usable scores"):
            await judge.judge_run(run_dir, _TextLLM("I cannot score this report."))

    async def test_garbage_brace_reply_raises_judge_error_not_decode_error(
        self, patched_runbooks, tmp_path
    ):
        run_dir = self._make_run(tmp_path, "r3-j2")
        with pytest.raises(judge.JudgeError, match="no usable scores"):
            await judge.judge_run(run_dir, _TextLLM("{garbage"))

    async def test_json_without_scores_raises_judge_error(self, patched_runbooks, tmp_path):
        run_dir = self._make_run(tmp_path, "r3-j3")
        with pytest.raises(judge.JudgeError, match="no usable scores"):
            await judge.judge_run(
                run_dir, _TextLLM('{"reasons": {"factual_accuracy": "fine"}}')
            )

    def test_parse_judge_json_garbage_returns_empty_dict(self):
        assert judge._parse_judge_json("{garbage") == {}
        assert judge._parse_judge_json("not json at all") == {}

    def test_judge_cli_exits_2_on_judge_error(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("PROWL_API_KEY", "p")
        monkeypatch.setenv("RESEARCH_LLM_API_KEY", "k")
        empty_run = tmp_path / "runs" / "r3-nope"
        empty_run.mkdir(parents=True)
        assert judge.main(["--run", str(empty_run)]) == 2
        assert "no report.md" in capsys.readouterr().err


class TestJudgeUsageRatioZeroBudget:
    # R2.5: budget.max_tool_calls=0 divided by zero in usage_ratio.

    def test_zero_call_budget_yields_null_ratio(self, tmp_path):
        from research_agent.runbook import Budget, Outputs, Runbook, RunbookMeta

        budget = Budget.model_construct(max_tool_calls=0, max_usd=1.0, max_minutes=30)
        meta = RunbookMeta.model_construct(
            name="zero", description="", version="1.0", inputs=[], tools=[],
            budget=budget, outputs=Outputs(report_template="t", formats=["markdown"]),
        )
        runbook = Runbook(meta=meta, body="", path=Path("zero/SKILL.md"))
        signals = judge.programmatic_signals(
            "no numbers here", Ledger(tmp_path / "ledger.json"),
            Checkpoint(run_id="z", runbook="zero"), runbook,
        )
        assert signals["budget"]["max_tool_calls"] == 0
        assert signals["budget"]["usage_ratio"] is None


class TestJudgeModelEnvOverride:
    # R2.5: RESEARCH_JUDGE_MODEL decouples the judge from the writer model.

    def test_judge_model_env_override(self):
        config = Config.from_env({
            "PROWL_API_KEY": "p",
            "RESEARCH_LLM_API_KEY": "l",
            "RESEARCH_JUDGE_MODEL": "judge-model",
        })
        assert config.llm_model_judge == "judge-model"
        assert config.llm_model_strong != "judge-model"

    def test_judge_model_defaults_to_strong(self):
        config = Config.from_env({
            "PROWL_API_KEY": "p",
            "RESEARCH_LLM_API_KEY": "l",
            "RESEARCH_LLM_MODEL_STRONG": "strong-x",
        })
        assert config.llm_model_judge == "strong-x"


class TestRewriteRefreshesHtml:
    # R2.4: rewrite_report overwrote report.md but left report.html stale.

    def _make_run(self, tmp_path: Path, run_id: str) -> Path:
        run_dir = tmp_path / "runs" / run_id
        store = ArtifactStore(run_dir)
        store.save_checkpoint(
            Checkpoint(run_id=run_id, runbook="mini-teardown",
                       brief={"competitors": ["a.com"]})
        )
        ledger = _one_claim_ledger(run_dir)
        ledger.save()
        (run_dir / "report.md").write_text("stale draft\n", encoding="utf-8")
        return run_dir

    async def test_rewrite_renders_html(self, patched_runbooks, tmp_path, fake_llm, monkeypatch):
        from research_agent.agent.writer import rewrite_report

        run_dir = self._make_run(tmp_path, "r3-rw1")
        fake_llm.text_queue = ["a.com attracts 150,000 visitors [C1]."]
        rendered: list[Path] = []
        monkeypatch.setattr(
            "research_agent.report.render.render_run", lambda p: rendered.append(Path(p))
        )

        outcome = await rewrite_report(fake_llm, tmp_path / "runs", "r3-rw1")

        assert rendered == [run_dir]
        assert "[C1]" in outcome.report_md

    async def test_rewrite_survives_html_render_failure(
        self, patched_runbooks, tmp_path, fake_llm, monkeypatch
    ):
        from research_agent.agent.writer import rewrite_report

        self._make_run(tmp_path, "r3-rw2")
        fake_llm.text_queue = ["a.com attracts 150,000 visitors [C1]."]

        def boom(_path):
            raise RuntimeError("render exploded")

        monkeypatch.setattr("research_agent.report.render.render_run", boom)

        outcome = await rewrite_report(fake_llm, tmp_path / "runs", "r3-rw2")
        assert "[C1]" in outcome.report_md


class TestRetryLoopHygiene:
    # R2.6: 408 is transient; a previous attempt's Retry-After must not leak
    # into a later transport failure; backoff carries jitter.

    async def test_http_408_is_retried(self, monkeypatch):
        client, calls = _client_with_post(monkeypatch, [
            httpx.Response(408, text="request timeout"),
            httpx.Response(200, json=_ok_payload()),
        ])

        async def fake_sleep(_d):
            pass

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        result = await client.complete([{"role": "user", "content": "hi"}], tier="cheap")
        assert result == "ok"
        assert len(calls) == 2
        await client.aclose()

    async def test_http_400_is_not_retried(self, monkeypatch):
        client, calls = _client_with_post(monkeypatch, [
            httpx.Response(400, text="bad request"),
        ])
        with pytest.raises(LLMError, match="HTTP 400"):
            await client.complete([{"role": "user", "content": "hi"}], tier="cheap")
        assert len(calls) == 1
        await client.aclose()

    async def test_stale_retry_after_not_applied_after_transport_error(self, monkeypatch):
        delays: list[float] = []

        async def fake_sleep(delay):
            delays.append(delay)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        client, calls = _client_with_post(monkeypatch, [
            httpx.Response(429, text="slow down", headers={"retry-after": "30"}),
            httpx.ConnectError("connection reset"),
            httpx.Response(200, json=_ok_payload()),
        ])
        result = await client.complete([{"role": "user", "content": "hi"}], tier="cheap")
        assert result == "ok"
        assert len(calls) == 3
        assert len(delays) == 2
        # Attempt 1's own Retry-After applies to its retry...
        assert delays[0] == 30.0
        # ...but the transport failure has no response of its own: applying
        # the stale Retry-After would pin the second delay at 30 as well.
        assert 1.0 <= delays[1] <= 3.0
        await client.aclose()


class TestReadTimeoutScaling:
    # R2.7: 120s read timeout is too tight for 8k-token strong generations.

    async def test_read_timeout_scales_with_max_tokens(self, monkeypatch):
        client, calls = _client_with_post(
            monkeypatch, [httpx.Response(200, json=_ok_payload())]
        )
        await client.complete(
            [{"role": "user", "content": "hi"}], tier="strong", max_tokens=8000
        )
        timeout = calls[0]["timeout"]
        assert timeout.read == 400.0
        assert timeout.connect == 120.0
        await client.aclose()

    async def test_small_max_tokens_keeps_default_read_timeout(self, monkeypatch):
        client, calls = _client_with_post(
            monkeypatch, [httpx.Response(200, json=_ok_payload())]
        )
        await client.complete(
            [{"role": "user", "content": "hi"}], tier="cheap", max_tokens=1000
        )
        assert calls[0]["timeout"].read == 120.0
        await client.aclose()

    async def test_no_max_tokens_uses_client_default(self, monkeypatch):
        client, calls = _client_with_post(
            monkeypatch, [httpx.Response(200, json=_ok_payload())]
        )
        await client.complete([{"role": "user", "content": "hi"}], tier="cheap")
        assert "timeout" not in calls[0]
        await client.aclose()


class TestCliHonesty:
    # R2.8: usage errors exit 2; crashes exit 1 AND mark the checkpoint
    # failed; string inputs keep their commas; status stops counting skipped
    # steps as completed.

    def test_parse_input_pairs_keeps_commas_in_string_values(self):
        from research_agent.__main__ import _parse_input_pairs

        inputs = _parse_input_pairs(["--market", "retail, DTC", "--competitors", "a.com,b.com"])
        assert inputs == {"market": "retail, DTC", "competitors": "a.com,b.com"}

    def test_parse_input_pairs_supports_key_equals_value(self):
        from research_agent.__main__ import _parse_input_pairs

        inputs = _parse_input_pairs(["--market=retail, DTC"])
        assert inputs == {"market": "retail, DTC"}

    def test_comma_values_split_only_for_list_typed_inputs(self, patched_runbooks):
        from research_agent.agent.orchestrator import build_brief
        from research_agent.runbook import get_runbook

        brief = build_brief(
            get_runbook("mini-teardown"),
            {"competitors": "a.com,b.com", "market": "retail, DTC"},
        )
        assert brief["competitors"] == ["a.com", "b.com"]
        assert brief["market"] == "retail, DTC"

    def test_run_unknown_runbook_exits_2(self, monkeypatch, capsys, tmp_path):
        from research_agent.__main__ import main

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PROWL_API_KEY", "p")
        monkeypatch.setenv("RESEARCH_LLM_API_KEY", "l")
        monkeypatch.setattr("research_agent.prowl_client.ProwlClient", _StubProwl)
        assert main(["run", "no-such-runbook", "--competitors", "a.com"]) == 2
        assert "unknown runbook" in capsys.readouterr().err

    def test_run_llm_error_marks_checkpoint_failed_and_exits_1(
        self, patched_runbooks, monkeypatch, capsys, tmp_path
    ):
        from research_agent.__main__ import main

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PROWL_API_KEY", "p")
        monkeypatch.setenv("RESEARCH_LLM_API_KEY", "l")
        monkeypatch.setattr("research_agent.prowl_client.ProwlClient", _StubProwl)
        store = ArtifactStore(tmp_path / "runs" / "r3-fail1")
        store.save_checkpoint(
            Checkpoint(run_id="r3-fail1", runbook="mini-teardown",
                       brief={"competitors": ["a.com"]})
        )

        async def boom(self, runbook_name, inputs, run_id=None):
            raise LLMError("provider blew up", retryable=False)

        monkeypatch.setattr("research_agent.agent.orchestrator.Orchestrator.run", boom)

        assert main(["run", "mini-teardown", "--run-id", "r3-fail1",
                     "--competitors", "a.com"]) == 1
        assert "provider blew up" in capsys.readouterr().err
        checkpoint = json.loads((tmp_path / "runs" / "r3-fail1" / "checkpoint.json").read_text())
        assert checkpoint["status"] == "failed"
        assert "provider blew up" in checkpoint["stop_reason"]

    def test_precondition_error_does_not_rewrite_finished_checkpoint(
        self, patched_runbooks, monkeypatch, tmp_path
    ):
        from research_agent.__main__ import main
        from research_agent.agent.orchestrator import OrchestratorError

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PROWL_API_KEY", "p")
        monkeypatch.setenv("RESEARCH_LLM_API_KEY", "l")
        monkeypatch.setattr("research_agent.prowl_client.ProwlClient", _StubProwl)
        done = Checkpoint(run_id="r3-done1", runbook="mini-teardown",
                          brief={"competitors": ["a.com"]})
        done.status = "complete"
        ArtifactStore(tmp_path / "runs" / "r3-done1").save_checkpoint(done)

        async def boom(self, runbook_name, inputs, run_id=None):
            raise OrchestratorError(f"run r3-done1 already finished with status 'complete'")

        monkeypatch.setattr("research_agent.agent.orchestrator.Orchestrator.run", boom)

        assert main(["run", "mini-teardown", "--run-id", "r3-done1",
                     "--competitors", "a.com"]) == 1
        checkpoint = json.loads((tmp_path / "runs" / "r3-done1" / "checkpoint.json").read_text())
        assert checkpoint["status"] == "complete"
        assert checkpoint["stop_reason"] is None

    def test_status_excludes_skipped_steps_from_completed(self, monkeypatch, capsys):
        from research_agent.__main__ import main

        fake_status = {
            "run_id": "r3-stat1", "runbook": "mini-teardown", "status": "partial",
            "completed_steps": [0, 1, 2], "planned_steps": 3,
            "skipped_steps": [
                {"index": 1, "step": "s1", "tool": "t", "reason": "failed"},
                {"index": 2, "step": "s2", "tool": "t", "reason": "failed"},
            ],
            "counters": {}, "duration_s": None, "stop_reason": "budget",
        }
        monkeypatch.setattr(
            "research_agent.mcp_server._status_dict", lambda run_id: fake_status
        )
        assert main(["status", "r3-stat1"]) == 0
        out = capsys.readouterr().out
        assert "1/3 completed, 2 skipped" in out
