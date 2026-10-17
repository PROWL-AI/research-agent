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


@pytest.fixture(autouse=True)
def _no_env_cap(monkeypatch):
    # A developer shell's RESEARCH_MAX_LLM_USD must not decide these tests.
    monkeypatch.delenv("RESEARCH_MAX_LLM_USD", raising=False)


class Provider:
    """Answers like the planner/extractor/writer would and bills `cost` per call
    (or the next of `costs`)."""

    def __init__(self, cost: float | None = 0.3, plan_steps: int = 2, script=None, costs=None,
                 report: str = "# Report\n\nVisits are 42 [C1].\n", truncate_writer: bool = False) -> None:
        self.cost = cost
        self.costs = list(costs or [])
        self.plan_steps = plan_steps
        self.requests: list[dict] = []
        self.script = list(script or [])
        self.report = report
        self.truncate_writer = truncate_writer

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
            content = self.report
            if self.truncate_writer and body.get("max_tokens") and "Write the report" in system:
                cost = self.costs.pop(0) if self.costs else self.cost
                return httpx.Response(200, json={"choices": [{"message": {"content": "# Partial draft [C1]"},
                                                              "finish_reason": "length"}],
                                                 "usage": {"prompt_tokens": 10, "completion_tokens": 10, "cost": cost}})
        cost = self.costs.pop(0) if self.costs else self.cost
        return httpx.Response(200, json=_completion(content, cost))


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
    # A 429 came back unbilled: recorded, but at 0 — rate limiting does not eat
    # the budget (wave-4 fix round; it used to keep its full estimate).
    assert (first.outcome, first.cost_basis, first.actual_usd, first.attempt_no) == ("http_error", "actual", 0.0, 1)
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


# ── wave-4 fix round: findings of the unit / seam / product readings ────────

def _big_runbook(patched_runbooks):
    """mini-teardown with room for many tool calls, so the LLM cap is what stops."""
    src = (patched_runbooks / "mini-teardown" / "SKILL.md").read_text()
    target = patched_runbooks / "mini-wide"
    target.mkdir(exist_ok=True)
    (target / "SKILL.md").write_text(src.replace("name: mini-teardown", "name: mini-wide")
                                     .replace("max_tool_calls: 2", "max_tool_calls: 10"))
    return "mini-wide"


async def test_a_retry_is_refused_before_it_is_sent():
    sent = []

    def handler(request):
        sent.append(request)
        raise httpx.ConnectError("down")  # no reply: the attempt keeps its estimate

    llm = LLMClient("http://llm.invalid", "test", "cheap", "strong")
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    estimate = pricing.estimate_call_usd("cheap", MSG, None)
    llm.meter = _meter(max_usd=estimate * 1.5 + 0.0001, reserve=0.0)
    with pytest.raises(LLMBudgetExceeded):
        await llm.complete(MSG, stage="extract")
    assert len(sent) == 1 and llm.meter.refusals == ["extract"]


async def test_once_research_is_refused_no_further_tool_is_paid_for(patched_runbooks, tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_NO_SUBAGENTS", "1")
    name = _big_runbook(patched_runbooks)
    # planner 0.50, extraction 0.22 → 0.72 < research limit 0.75, but the next
    # extraction's estimate does not fit: it is refused, and dispatch stops.
    provider = Provider(costs=[0.50, 0.22], cost=0.01, plan_steps=5)
    prowl = FakeProwl()
    result = await Orchestrator(prowl, _client(provider), runs_root=tmp_path / "runs").run(
        name, BRIEF, run_id="latch", max_llm_usd=1.0)
    states = [s.state for s in ArtifactStore(tmp_path / "runs" / "latch").load_checkpoint().steps]
    assert result.terminal_code == "budget_llm"
    assert len(prowl.tool_calls) == 2, states
    assert states[2:] == ["skipped_budget"] * 3


async def test_a_refused_repair_or_citation_pass_ends_the_run_partial(patched_runbooks, tmp_path):
    # planner, extraction and draft fit; the draft has an uncited number, the
    # repair pass is refused — the run must not report "completed".
    provider = Provider(costs=[0.30, 0.30, 0.30], cost=0.30, plan_steps=1,
                        report="# Report\n\nVisits are 42 [C1]. Revenue is 999 dollars.\n")
    result = await Orchestrator(FakeProwl(), _client(provider), runs_root=tmp_path / "runs").run(
        "mini-teardown", BRIEF, run_id="quiet", max_llm_usd=1.0)
    assert (result.status, result.terminal_code) == ("partial", "budget_llm")
    assert result.stats["llm_budget"]["refused_stages"]
    from research_agent.agent.writer import partial_disclosed

    assert partial_disclosed((tmp_path / "runs" / "quiet" / "report.md").read_text())


async def test_a_draft_written_as_complete_says_partial_when_its_repair_is_refused(patched_runbooks, tmp_path):
    """W6 seam fix: the writer is told only what was partial before it wrote; a
    repair the cap refuses afterwards still leaves report.md saying partial."""
    from research_agent.agent.writer import partial_disclosed

    provider = Provider(costs=[0.30, 0.30, 0.395], cost=0.30, plan_steps=1,
                        report="# Report\n\n## Summary\n\nVisits are 42 [C1]. Revenue is $999 a month.\n")
    llm = _client(provider, model_cheap="deepseek/deepseek-v4.1-flash", model_strong="xiaomi/mimo-v2.6-pro")
    result = await Orchestrator(FakeProwl(), llm, runs_root=tmp_path / "runs").run(
        "mini-teardown", BRIEF, run_id="quiet2", max_llm_usd=1.0)
    assert (result.status, result.terminal_code) == ("partial", "budget_llm")
    assert "writer" not in result.stats["llm_budget"]["refused_stages"]  # the draft was written
    report = (tmp_path / "runs" / "quiet2" / "report.md").read_text()
    assert report.startswith("# Report\n\n**PARTIAL RUN:** max_llm_usd") and partial_disclosed(report)
    assert "Visits are 42 [C1]" in report


async def test_a_replanned_run_keeps_its_cap_and_spend(patched_runbooks, tmp_path):
    runs = tmp_path / "runs"
    tiny = Provider(cost=0.05, plan_steps=1)
    first = await Orchestrator(FakeProwl(), _client(tiny), runs_root=runs).run(
        "mini-teardown", BRIEF, run_id="replan", max_llm_usd=0.0001)  # the planner is refused
    assert first.terminal_code == "budget_llm"
    cp = ArtifactStore(runs / "replan").load_checkpoint()
    assert cp.llm_cap_usd == 0.0001 and not [a for a in cp.attempts if a.step_id == "writer"]
    assert "evidence only" in (runs / "replan" / "report.md").read_text()
    await Orchestrator(FakeProwl(), _client(tiny), runs_root=runs).run("mini-teardown", BRIEF, run_id="replan")
    again = ArtifactStore(runs / "replan").load_checkpoint()
    assert again.llm_cap_usd == 0.0001  # not the default


async def test_a_resume_that_gathers_nothing_keeps_the_paid_report(patched_runbooks, tmp_path):
    runs = tmp_path / "runs"
    provider = Provider(cost=0.4, plan_steps=2)

    def priced():  # listed models: the writer's estimate is small enough to fit the reserve
        return _client(provider, model_cheap="deepseek/deepseek-v4.1-flash", model_strong="xiaomi/mimo-v2.6-pro")

    await Orchestrator(FakeProwl(), priced(), runs_root=runs).run(
        "mini-teardown", BRIEF, run_id="keep", max_llm_usd=1.0)
    report = (runs / "keep" / "report.md").read_bytes()
    assert report.startswith(b"# Report")
    before = ArtifactStore(runs / "keep").load_checkpoint().stats["citation_fidelity"]
    provider.cost = 5.0  # whatever runs now could not be afforded
    await Orchestrator(FakeProwl(), priced(), runs_root=runs).run("mini-teardown", BRIEF, run_id="keep")
    assert (runs / "keep" / "report.md").read_bytes() == report
    assert ArtifactStore(runs / "keep").load_checkpoint().stats["citation_fidelity"] == before


async def test_rewrite_spends_from_the_run_ledger_and_refuses_without_budget(patched_runbooks, tmp_path):
    from research_agent.agent.writer import RewriteError, rewrite_report

    runs = tmp_path / "runs"
    provider = Provider(cost=0.45, plan_steps=1)
    await Orchestrator(FakeProwl(), _client(provider), runs_root=runs).run(
        "mini-teardown", BRIEF, run_id="rw", max_llm_usd=1.0)  # ends evidence-only
    store = ArtifactStore(runs / "rw")
    before = store.load_checkpoint().spend_usd("llm")
    report = (runs / "rw" / "report.md").read_bytes()
    with pytest.raises(RewriteError, match="LLM budget"):
        await rewrite_report(_client(provider), runs, "rw")  # same cap: no room
    assert (runs / "rw" / "report.md").read_bytes() == report
    cheap = Provider(cost=0.01, plan_steps=1)
    await rewrite_report(_client(cheap), runs, "rw", max_llm_usd=5.0)
    after = store.load_checkpoint()
    assert after.spend_usd("llm") > before and after.stats["llm_budget"]["max_llm_usd"] == 5.0
    assert (runs / "rw" / "report.md").read_text().startswith("# Report")


async def test_a_refused_longer_draft_ships_the_paid_truncated_one(patched_runbooks, tmp_path):
    # planner .3 + extraction .3; the 8k draft (.05) comes back truncated; the
    # 12k retry's estimate does not fit — the first draft ships.
    provider = Provider(costs=[0.30, 0.30, 0.05], cost=0.05, plan_steps=1, truncate_writer=True)
    llm = _client(provider, model_strong="deepseek/deepseek-v4.1-flash")
    result = await Orchestrator(FakeProwl(), llm, runs_root=tmp_path / "runs").run(
        "mini-teardown", BRIEF, run_id="trunc", max_llm_usd=0.66)
    report = (tmp_path / "runs" / "trunc" / "report.md").read_text()
    assert "# Partial draft" in report and "evidence only" not in report
    assert result.terminal_code == "budget_llm"


def test_infinite_caps_are_refused_everywhere():
    from research_agent.runbook import Budget

    for bad in (float("inf"), float("nan"), 0, -1):
        with pytest.raises(ConfigError):
            resolve_llm_cap(bad, None, None, {})
    with pytest.raises(ConfigError):
        resolve_llm_cap(None, None, None, {"RESEARCH_MAX_LLM_USD": "inf"})
    with pytest.raises(ConfigError):
        resolve_llm_cap(None, float("inf"), None, {})
    with pytest.raises(Exception):
        Budget(max_tool_calls=1, max_usd=1, max_minutes=1, max_llm_usd=float("inf"))


async def test_mcp_refuses_a_bad_cap_before_handing_out_a_job(patched_runbooks, monkeypatch):
    import research_agent.mcp_server as srv

    monkeypatch.setenv("RESEARCH_MAX_LLM_USD", "lots")
    with pytest.raises(ValueError, match="RESEARCH_MAX_LLM_USD"):
        await srv.research_run("mini-teardown", BRIEF)
    monkeypatch.delenv("RESEARCH_MAX_LLM_USD")
    with pytest.raises(ValueError, match="max_llm_usd"):
        await srv.research_run("mini-teardown", BRIEF, max_llm_usd=float("inf"))


def test_stdio_run_schema_matches_the_tool_signature():
    import inspect
    from pathlib import Path

    import research_agent.mcp_server as srv

    schema = json.loads((Path(__file__).resolve().parent.parent / "fabric" / "schemas"
                         / "capability-input.schema.json").read_text())
    assert set(schema["properties"]) == set(inspect.signature(srv.research_run).parameters)


def _capture_run(monkeypatch):
    from research_agent.agent import orchestrator as orch_mod

    seen = []

    async def fake_run(self, runbook, inputs, run_id=None, *, max_llm_usd=None):
        seen.append(max_llm_usd)
        raise orch_mod.OrchestratorError("stop here")

    monkeypatch.setattr(orch_mod.Orchestrator, "run", fake_run)
    return seen, orch_mod.OrchestratorError


def test_the_cap_reaches_the_run_from_the_cli(patched_runbooks, monkeypatch, tmp_path):
    from research_agent.__main__ import main

    seen, _ = _capture_run(monkeypatch)
    monkeypatch.setattr("research_agent.prowl_client.ProwlClient", lambda **kwargs: FakeProwl())
    monkeypatch.setattr("research_agent.__main__._reconcile", lambda root: None)
    monkeypatch.setenv("PROWL_API_KEY", "test-not-a-key")
    monkeypatch.setenv("RESEARCH_LLM_API_KEY", "test-not-a-key")
    monkeypatch.setenv("RESEARCH_RUNS_DIR", str(tmp_path / "runs"))
    main(["run", "mini-teardown", "--max-llm-usd", "2.5", "--competitors", "a.com"])
    assert seen == [2.5]
    assert main(["run", "mini-teardown", "--max-llm-usd", "inf"]) == 2


async def test_the_cap_reaches_the_run_from_mcp(patched_runbooks, monkeypatch, tmp_path):
    import research_agent.mcp_server as srv
    from research_agent.config import Config

    seen, error = _capture_run(monkeypatch)
    monkeypatch.setenv("RESEARCH_RUNS_DIR", str(tmp_path / "runs"))
    config = Config(prowl_api_key="t", prowl_mcp_url="http://unused.invalid", llm_api_key="t",
                    llm_base_url="http://unused.invalid", llm_model="cheap", llm_model_strong="strong")
    monkeypatch.setattr(srv, "_config_from_env", lambda: config)
    monkeypatch.setattr(srv, "_make_prowl", lambda config: FakeProwl())
    with pytest.raises(error):
        await srv.research_run("mini-teardown", BRIEF, wait=True, max_llm_usd=3.5)
    assert seen == [3.5]


async def test_a_checkpoint_write_failure_in_the_meter_is_never_a_step_failure(tmp_path):
    from research_agent.evidence.store import CheckpointWriteError

    llm = _client(Provider(cost=0.01))

    def broken():
        raise OSError("disk full")

    llm.meter = _meter(5.0, 1.0)
    llm.meter.persist = broken
    with pytest.raises(CheckpointWriteError):
        await llm.complete(MSG, stage="extract")


def test_estimates_err_high_for_unlisted_models_and_non_ascii_text():
    assert pricing.UNKNOWN_PRICE[0] >= max(p[0] for p in pricing.PRICES.values())
    assert pricing.UNKNOWN_PRICE[1] >= max(p[1] for p in pricing.PRICES.values())
    latin = [{"role": "user", "content": "a" * 4000}]
    cyrillic = [{"role": "user", "content": "я" * 4000}]
    assert pricing.estimate_call_usd("qwen/qwen3.8-flash", cyrillic, 0) >= 1.9 * pricing.estimate_call_usd(
        "qwen/qwen3.8-flash", latin, 0)


def test_openrouter_is_asked_for_the_cost(monkeypatch):
    import asyncio

    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_completion("ok", 0.001))

    llm = LLMClient("https://openrouter.ai/api/v1", "test", "cheap", "strong")
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    asyncio.run(llm.complete(MSG))
    other = LLMClient("https://llm.example/v1", "test", "cheap", "strong")
    other._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    asyncio.run(other.complete(MSG))
    assert bodies[0]["usage"] == {"include": True} and "usage" not in bodies[1]


async def test_a_billed_planner_failure_is_still_counted_after_a_replan(patched_runbooks, tmp_path):
    from research_agent.agent.orchestrator import OrchestratorError

    runs = tmp_path / "runs"
    broken = Provider(cost=0.4, plan_steps=1)
    broken.plan_steps = None

    def no_plan(request):  # the planner answers, is billed, and returns no plan
        body = json.loads(request.content)
        if "response_format" in body and "evidence-ledger" not in body["messages"][0]["content"]:
            return httpx.Response(200, json=_completion(json.dumps({"nothing": True}), 0.4))
        return broken(request)

    llm = LLMClient("http://llm.invalid", "test", "cheap", "strong")
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(no_plan))
    with pytest.raises(OrchestratorError):
        await Orchestrator(FakeProwl(), llm, runs_root=runs).run("mini-teardown", BRIEF, run_id="billed", max_llm_usd=2.0)
    await Orchestrator(FakeProwl(), _client(Provider(cost=0.01, plan_steps=1)), runs_root=runs).run(
        "mini-teardown", BRIEF, run_id="billed")
    cp = ArtifactStore(runs / "billed").load_checkpoint()
    assert cp.llm_cap_usd == 2.0
    assert cp.spend_usd("llm") >= 0.4  # the first planner call is still on the books
