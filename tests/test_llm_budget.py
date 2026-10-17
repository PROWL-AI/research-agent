"""Wave 4 (KA-G01): the run's own LLM spend is capped by max_llm_usd.

A real LLMClient talks to an httpx MockTransport that bills a fixed cost per
call, so every assertion is about money the ledger recorded, not about a fake.
"""

from __future__ import annotations

import json

import httpx
import pytest

from research_agent import pricing
from research_agent.agent.orchestrator import Orchestrator
from research_agent.config import ConfigError, resolve_llm_cap, writer_reserve
from research_agent.evidence.store import ArtifactStore, AttemptRecord
from research_agent.llm import LLMBudgetExceeded, LLMClient, LlmMeter

from conftest import FakeProwl

TOOL = "spyfu_get_domain_stats"
BRIEF = {"competitors": ["example.com"]}


def _completion(content: str, cost: float | None, tokens=(100, 50)) -> dict:
    usage = {"prompt_tokens": tokens[0], "completion_tokens": tokens[1]}
    if cost is not None:
        usage["cost"] = cost
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}], "usage": usage}


class Provider:
    """Answers like the planner/extractor/writer would and bills `cost` per call."""

    def __init__(self, cost: float | None = 0.3, plan_steps: int = 2, script=None) -> None:
        self.cost = cost
        self.plan_steps = plan_steps
        self.requests: list[dict] = []
        self.script = list(script or [])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        if self.script:
            status, payload = self.script.pop(0)
            return httpx.Response(status, json=payload)
        system = body["messages"][0]["content"]
        json_mode = "response_format" in body
        if json_mode and "evidence-ledger claims" in system:
            content = json.dumps({"claims": [{"claim": "Visits 42", "subject": "example.com visits",
                                              "value": 42, "unit": "visits"}]})
        elif json_mode and "citation" in system.lower():
            content = json.dumps({"verdicts": []})
        elif json_mode:
            content = json.dumps({"plan": [
                {"step": f"baseline-{i}", "tool": TOOL, "arguments": {"domain": f"s{i}.example.com"}}
                for i in range(self.plan_steps)]})
        else:
            content = "# Report\n\nVisits are 42 [C1].\n"
        return httpx.Response(200, json=_completion(content, self.cost))


def _client(provider: Provider, model_cheap="cheap", model_strong="strong") -> LLMClient:
    llm = LLMClient("http://llm.invalid", "test", model_cheap, model_strong)
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    return llm


def _meter(max_usd: float, reserve: float) -> LlmMeter:
    attempts: list = []
    counter = iter(range(1, 10_000))
    return LlmMeter(max_usd=max_usd, reserve_usd=reserve, attempts=attempts, persist=lambda: None,
                    record_type=AttemptRecord, new_id=lambda: f"llm#{next(counter)}")


MSG = [{"role": "user", "content": "hi"}]


async def test_research_calls_stop_before_the_cap_and_the_writer_spends_the_reserve():
    provider = Provider(cost=0.36)
    llm = _client(provider)
    llm.meter = _meter(1.0, 0.25)  # research limit 0.75
    await llm.complete(MSG, stage="extract")
    await llm.complete(MSG, stage="extract")
    assert llm.meter.spend() == pytest.approx(0.72)
    sent = len(provider.requests)
    with pytest.raises(LLMBudgetExceeded) as refused:
        await llm.complete(MSG, stage="extract")
    assert len(provider.requests) == sent  # refused BEFORE sending
    assert refused.value.stage == "extract" and "max_llm_usd=1.0" in str(refused.value)
    await llm.complete(MSG, stage="writer")  # 0.72 + estimate fits under the full cap
    assert llm.meter.spend() == pytest.approx(1.08)


async def test_every_retry_is_an_attempt_and_counts(monkeypatch):
    provider = Provider(script=[(429, {"error": "rate"}), (200, _completion("ok", 0.01))])
    llm = _client(provider)
    llm.meter = _meter(5.0, 1.0)

    async def no_sleep(_):
        return None

    monkeypatch.setattr("research_agent.llm.asyncio.sleep", no_sleep)
    assert await llm.complete(MSG, stage="extract") == "ok"
    first, second = [a for a in llm.meter.attempts if a.kind == "llm"]
    assert (first.outcome, first.cost_basis, first.attempt_no) == ("transport_error", "unknown", 1)
    assert first.spend_usd > 0  # a lost reply keeps its estimate: it may have been billed
    assert (second.outcome, second.cost_basis, second.actual_usd) == ("ok", "actual", 0.01)


async def test_a_missing_price_is_never_zero():
    llm = _client(Provider(cost=None))  # provider reports tokens, no cost
    llm.meter = _meter(5.0, 1.0)
    await llm.complete(MSG, stage="extract")  # model "cheap" is not in the price table
    unknown = llm.meter.attempts[-1]
    assert unknown.cost_basis == "unknown" and unknown.estimate_usd > 0
    assert unknown.estimate_usd == pricing.cost_usd("no-such-model", 100, 50)[0]
    known = _client(Provider(cost=None), model_cheap="deepseek/deepseek-v4.1-flash")
    known.meter = _meter(5.0, 1.0)
    await known.complete(MSG, stage="extract")
    assert known.meter.attempts[-1].cost_basis == "estimate"
    assert known.meter.attempts[-1].estimate_usd < unknown.estimate_usd


async def test_the_run_stops_research_at_the_llm_cap_and_resumes_without_paying_twice(patched_runbooks, tmp_path):
    runs = tmp_path / "runs"
    provider = Provider(cost=0.4, plan_steps=2)
    prowl = FakeProwl()
    result = await Orchestrator(prowl, _client(provider), runs_root=runs).run(
        "mini-teardown", BRIEF, run_id="capped", max_llm_usd=1.0)
    # planner 0.4 + extraction 0.4 = 0.8 >= research limit 0.75 → step 2 not dispatched
    assert (result.status, result.terminal_code) == ("partial", "budget_llm")
    assert len(prowl.tool_calls) == 1
    checkpoint = ArtifactStore(runs / "capped").load_checkpoint()
    assert checkpoint.llm_cap_usd == 1.0
    assert [s.state for s in checkpoint.steps] == ["completed", "skipped_budget"]
    assert result.stats["llm_budget"]["spend_usd"] == pytest.approx(checkpoint.spend_usd("llm"))
    assert result.stats["llm_budget"]["cost_source"] == "server"

    # Same cap: the recorded spend is read back — nothing more is dispatched.
    again_prowl = FakeProwl()
    again = await Orchestrator(again_prowl, _client(provider), runs_root=runs).run("mini-teardown", BRIEF, run_id="capped")
    assert again.terminal_code == "budget_llm" and again_prowl.tool_calls == []

    # A larger cap finishes the skipped step only.
    more_prowl = FakeProwl()
    done = await Orchestrator(more_prowl, _client(provider), runs_root=runs).run(
        "mini-teardown", BRIEF, run_id="capped", max_llm_usd=10.0)
    assert done.status == "complete" and len(more_prowl.tool_calls) == 1


async def test_when_even_the_reserve_is_gone_the_evidence_still_ships(patched_runbooks, tmp_path):
    runs = tmp_path / "runs"
    provider = Provider(cost=0.45, plan_steps=1)
    result = await Orchestrator(FakeProwl(), _client(provider), runs_root=runs).run(
        "mini-teardown", BRIEF, run_id="no-writer", max_llm_usd=1.0)
    # planner 0.45 + extraction 0.45 = 0.9; the writer's estimate does not fit under 1.0
    assert result.terminal_code == "budget_llm"
    report = (runs / "no-writer" / "report.md").read_text()
    assert "evidence only" in report and "[C1]" in report and "Visits 42" in report


def test_the_cap_resolves_caller_then_env_then_recorded_then_runbook_then_default():
    assert resolve_llm_cap(2.0, 3.0, 4.0, {"RESEARCH_MAX_LLM_USD": "9"}) == (2.0, "caller")
    assert resolve_llm_cap(None, 3.0, 4.0, {"RESEARCH_MAX_LLM_USD": "9"}) == (9.0, "env")
    assert resolve_llm_cap(None, 3.0, 4.0, {}) == (3.0, "checkpoint")
    assert resolve_llm_cap(None, None, 4.0, {}) == (4.0, "runbook")
    assert resolve_llm_cap(None, None, None, {})[1] == "default"
    with pytest.raises(ConfigError):
        resolve_llm_cap(None, None, None, {"RESEARCH_MAX_LLM_USD": "zero"})
    with pytest.raises(ConfigError):
        resolve_llm_cap(-1.0, None, None, {})
    assert writer_reserve(1.0) == 0.25 and writer_reserve(100.0) == 1.0
