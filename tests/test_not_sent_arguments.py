"""B-070 and B-071: arguments a provider refuses and bills are never sent.

B-065 stopped an unresolved ``{{name}}`` from being sent. The saved runs show the
planner writing template text in other shapes too, and the provider taking each one
as a value: refused and billed, or worse, "completed" (gemini_analyze_website read
the literal "[substitute full firecrawl_scrape_website output ...]" on
accept-teardown-20261021b and its answer became claims). Every argument below is
copied from a saved run. B-071: `tiktok_ads_library` refuses `country: "US"` (HTTP
400, five billed calls on accept-subscription-20261021 and -b) while its schema
offers 'US' as the example.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent.agent import bindings, tool_limits
from research_agent.agent.orchestrator import Orchestrator

from conftest import FakeLLM, FakeProwl
from test_subagents import _write_runbook

TOOL = "spyfu_get_domain_stats"
BRIEF = {"competitors": ["a.com"]}

#: Arguments that were sent on live runs and are template text, not values.
SENT_TEMPLATES = [
    "[substitute landing_page_url of the longest-running active monday.com ad from transform_ads_health]",
    "[substitute full firecrawl_scrape_website output for clickup.com from the scrape_clickup step]",
    "<video_id from youtube_search result — most recent official Novo Nordisk investor call>",
    "<governance / remuneration report URL from search or IR map>",
    "{youtube_search.latest_official_call_video_id}",
    "PLACEHOLDER_FROM_STEP_22",
]

#: Real values the same runs sent; none of them is template text.
REAL_VALUES = [
    '"Novo Nordisk" going concern',
    "Novo Nordisk auditor resigned OR going concern OR restatement",
    "site:reddit.com headspace [2026]",
    "placeholder text generator",
    "https://www.novonordisk.com/investors.html",
    '{"a": 1}',
    "price < 10 from 5 > 2",
    "https://apps.apple.com/us/app/id{{balance_apple_id}}",  # a {{name}}: B-065's path, not this one
    # shapes the unit verifier found the first patterns flagged (2026-10-22)
    "input[placeholder='Email']",
    "<input placeholder='Search'>",
    "[Substitute Teacher] movie",
    "how to [insert] a row",
    "[fill in the blank] worksheet",
    "<john@from.com>",
    # prompt-style text for LLM-backed tools (seam verifier, 2026-10-22): a shape inside prose is text
    "Extract {company.name} and {company.hq} from the page",
    "github {user.login}",
    "List each plan as <plan name from the pricing table>",
]


@pytest.mark.parametrize("value", SENT_TEMPLATES)
def test_template_text_seen_on_live_runs_is_found(value):
    assert bindings.template_text({"arg": value}) == [value]
    assert bindings.template_text({"nested": [{"arg": f"  {value} "}]})


@pytest.mark.parametrize("value", [SENT_TEMPLATES[0], SENT_TEMPLATES[5]])
def test_an_instruction_or_placeholder_inside_a_url_is_found(value):
    assert bindings.template_text({"url": f"https://x.com/{value}"})


@pytest.mark.parametrize("value", REAL_VALUES)
def test_real_values_are_not_template_text(value):
    assert bindings.template_text({"arg": value}) == []


def test_template_text_stays_linear_on_a_long_argument():
    """An unbounded pattern took 30 s on 136 KB and stalled every worker of the segment."""
    import time

    value = "<a " + "data from source " * 8000
    started = time.perf_counter()
    bindings.template_text({"a": value})
    assert time.perf_counter() - started < 0.5


def test_the_tiktok_country_limit_refuses_us_and_takes_all_and_europe():
    assert tool_limits.refused("tiktok_ads_library", {"query": "Calm", "country": "US"}) == ["country='US'"]
    for ok in ("all", "DE", "GB"):
        assert tool_limits.refused("tiktok_ads_library", {"query": "Calm", "country": ok}) == []
    assert tool_limits.refused("tiktok_ads_library", {"query": "Calm"}) == []  # the provider default
    assert tool_limits.refused("meta_ad_library", {"country": "US"}) == []  # no limit known: sent


def test_the_planner_is_told_the_limits_of_its_runbook_tools():
    notes = tool_limits.planner_notes(["meta_ad_library", "tiktok_ads_library"])
    assert notes.startswith("- `tiktok_ads_library` `country`:") and "`all`" in notes
    assert tool_limits.planner_notes(["meta_ad_library"]) == ""


# ── run ────────────────────────────────────────────────────────────────────


@pytest.fixture
def lookup_runbook(patched_runbooks) -> Path:
    _write_runbook(patched_runbooks, "notsent-lookup", 60, effort="lookup")
    return patched_runbooks


@pytest.fixture
def domain_limit(monkeypatch):
    """A known limit on the test tool, so a run exercises the dispatch guard."""
    limit = tool_limits.ArgumentLimit(allowed=frozenset({"a.com", "b.com"}), note="only a.com or b.com",
                                      source="test")
    monkeypatch.setitem(tool_limits.LIMITS, TOOL, {"domain": limit})


def _checkpoint(runs: Path, run_id: str) -> dict:
    return json.loads((runs / run_id / "checkpoint.json").read_text())


def _step(checkpoint: dict, name: str) -> dict:
    return next(s for s in checkpoint["steps"] if s["step"] == name)


@pytest.mark.parametrize("optional, state", [(True, "skipped_on_error"), (False, "failed")])
async def test_a_step_with_template_text_is_never_sent(lookup_runbook, tmp_path, optional, state):
    runs = tmp_path / "runs"
    prowl = FakeProwl()
    llm = FakeLLM()
    templated = {"step": "templated", "tool": TOOL, "arguments": {"domain": SENT_TEMPLATES[0]}}
    if optional:
        templated["on_error_skip"] = True
    llm.plan_payload = {"plan": [templated, {"step": "after", "tool": TOOL, "arguments": {"domain": "b.com"}}]}
    result = await Orchestrator(prowl, llm, runs_root=runs).run("notsent-lookup", BRIEF, run_id=f"tpl-{state}")

    assert [c["arguments"]["domain"] for c in prowl.tool_calls] == ["b.com"]
    step = _step(_checkpoint(runs, f"tpl-{state}"), "templated")
    assert step["state"] == state
    assert "not sent" in step["reason"] and "template text" in step["reason"]
    assert step["attempt_ids"] == []  # no attempt, no bill
    if not optional:
        assert (result.status, result.terminal_code) == ("partial", "step_failed")


async def test_a_value_the_provider_is_known_to_refuse_is_never_sent(lookup_runbook, tmp_path, domain_limit):
    runs = tmp_path / "runs"
    prowl = FakeProwl()
    llm = FakeLLM()
    llm.plan_payload = {"plan": [
        {"step": "refused", "tool": TOOL, "arguments": {"domain": "us.com"}, "on_error_skip": True},
        {"step": "after", "tool": TOOL, "arguments": {"domain": "b.com"}},
    ]}
    await Orchestrator(prowl, llm, runs_root=runs).run("notsent-lookup", BRIEF, run_id="limit")

    assert [c["arguments"]["domain"] for c in prowl.tool_calls] == ["b.com"]
    step = _step(_checkpoint(runs, "limit"), "refused")
    assert step["state"] == "skipped_on_error"
    assert step["reason"] == f"not sent: {TOOL} does not take domain='us.com' (a known provider limit)"
    assert step["attempt_ids"] == []


async def test_not_sent_steps_do_not_count_as_refusals(lookup_runbook, tmp_path):
    """Six required template-text steps in a row are not six refusals: nothing was sent."""
    runs = tmp_path / "runs"
    prowl = FakeProwl()
    llm = FakeLLM()
    steps = [{"step": f"t{i}", "tool": TOOL, "arguments": {"domain": f"PLACEHOLDER_FROM_STEP_{i}"}} for i in range(6)]
    steps.append({"step": "after", "tool": TOOL, "arguments": {"domain": "b.com"}})
    llm.plan_payload = {"plan": steps}
    await Orchestrator(prowl, llm, runs_root=runs).run("notsent-lookup", BRIEF, run_id="no-cascade")
    assert [c["arguments"]["domain"] for c in prowl.tool_calls] == ["b.com"]
    assert _step(_checkpoint(runs, "no-cascade"), "after")["state"] == "completed"


async def test_the_planner_prompt_carries_the_limits_of_allowlisted_tools(lookup_runbook, tmp_path, domain_limit):
    llm = FakeLLM()
    llm.plan_payload = {"plan": [{"step": "s", "tool": TOOL, "arguments": {"domain": "a.com"}}]}
    await Orchestrator(FakeProwl(), llm, runs_root=tmp_path / "runs").run("notsent-lookup", BRIEF, run_id="prompt")
    planner = next(c for c in llm.calls if "Output the plan JSON now." in c["messages"][-1]["content"])
    assert "## Argument limits the schemas do not state" in planner["messages"][-1]["content"]
    assert "only a.com or b.com" in planner["messages"][-1]["content"]


def test_a_direct_tool_request_with_a_known_refused_value_is_refused_before_a_job(tmp_path, monkeypatch):
    """research.tools.call dispatches params directly: a known-refused value is refused before a
    job exists; template text is the caller's own choice there; a replay answers its job."""
    from research_agent.service.runtime import Runtime, refuse_known_limits
    from research_agent.service.store import Store

    with pytest.raises(ValueError, match="known provider limit"):
        refuse_known_limits({"kind": "tool", "tool": "tiktok_ads_library", "params": {"query": "x", "country": "US"}})
    refuse_known_limits({"kind": "tool", "tool": "tiktok_ads_library", "params": {"query": "x", "country": "fr"}})
    refuse_known_limits({"kind": "tool", "tool": TOOL, "params": {"domain": "PLACEHOLDER text generator"}})

    monkeypatch.setenv("PROWL_API_KEY", "test-key")
    rt = Runtime(Store(tmp_path))
    bad = {"kind": "tool", "tool": "tiktok_ads_library", "params": {"query": "x", "country": "US"}}
    with pytest.raises(ValueError, match="known provider limit"):
        rt.create(bad, "direct-1")
    assert rt.store.jobs() == []


async def test_the_writer_is_told_a_not_sent_step_is_the_plan_gap_not_a_refusal(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    llm = FakeLLM()
    llm.plan_payload = {"plan": [
        {"step": "templated", "tool": TOOL, "arguments": {"domain": SENT_TEMPLATES[0]}},
        {"step": "after", "tool": TOOL, "arguments": {"domain": "b.com"}},
    ]}
    await Orchestrator(FakeProwl(), llm, runs_root=runs).run("notsent-lookup", BRIEF, run_id="writer")
    writer = [m["content"] for call in llm.calls for m in call["messages"]
              if m["role"] == "system" and "PARTIAL RUN" in m["content"]]
    assert writer, "the writer got no partial note"
    sent_line = next(line for line in writer[-1].splitlines() if "templated" in line)
    assert sent_line.startswith("These steps were not sent")
    assert "refused by the data source" not in writer[-1]


def test_the_country_limit_ignores_case():
    assert tool_limits.refused("tiktok_ads_library", {"country": "fr"}) == []
    assert tool_limits.refused("tiktok_ads_library", {"country": "us"}) == ["country='us'"]


async def test_the_writer_is_told_what_a_limited_source_covers(lookup_runbook, tmp_path, monkeypatch):
    limit = tool_limits.ArgumentLimit(allowed=frozenset({"all"}), note="n", source="test",
                                      coverage="results cover Europe only")
    monkeypatch.setitem(tool_limits.LIMITS, TOOL, {"country": limit})
    llm = FakeLLM()
    llm.plan_payload = {"plan": [{"step": "s", "tool": TOOL, "arguments": {"domain": "a.com", "country": "all"}}]}
    await Orchestrator(FakeProwl(), llm, runs_root=tmp_path / "runs").run("notsent-lookup", BRIEF, run_id="cover")
    writer = [m["content"] for call in llm.calls for m in call["messages"] if "## Source coverage" in m["content"]]
    assert writer and "results cover Europe only" in writer[-1]
    assert tool_limits.coverage_notes(["meta_ad_library"]) == []


async def test_a_refused_direct_call_answers_a_tool_error_on_the_wire(tmp_path, monkeypatch):
    """The MCP shape the docs name: a tool result with isError and code request-rejected."""
    from research_agent.service.protocol import Protocol
    from research_agent.service.runtime import Runtime
    from research_agent.service.store import Store

    monkeypatch.setenv("PROWL_API_KEY", "test-key")
    rt = Runtime(Store(tmp_path))
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "research.tools.call",
        "arguments": {"tool": "tiktok_ads_library", "params": {"query": "x", "country": "US"}, "idempotencyKey": "wire-1"}}}
    got, status = await Protocol(rt).handle(body, {})
    assert status == 200 and got["result"]["isError"] is True
    error = got["result"]["structuredContent"]["error"]
    assert error["code"] == "request-rejected" and "known provider limit" in error["message"]
    assert rt.store.jobs() == []


async def test_an_optional_not_sent_step_in_a_complete_run_reaches_the_writer(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    llm = FakeLLM()
    llm.plan_payload = {"plan": [
        {"step": "templated", "tool": TOOL, "arguments": {"domain": SENT_TEMPLATES[0]}, "on_error_skip": True},
        {"step": "after", "tool": TOOL, "arguments": {"domain": "b.com"}},
    ]}
    result = await Orchestrator(FakeProwl(), llm, runs_root=runs).run("notsent-lookup", BRIEF, run_id="complete")
    assert result.status == "complete"
    writer = [m["content"] for call in llm.calls for m in call["messages"]
              if m["role"] == "system" and "STEPS NOT SENT" in m["content"]]
    assert writer and "templated" in writer[-1]


async def test_a_limited_value_is_sent_in_the_providers_spelling(lookup_runbook, tmp_path, monkeypatch):
    limit = tool_limits.ArgumentLimit(allowed=frozenset({"all", "FR"}), note="n", source="test")
    monkeypatch.setitem(tool_limits.LIMITS, TOOL, {"country": limit})
    prowl = FakeProwl()
    llm = FakeLLM()
    llm.plan_payload = {"plan": [{"step": "s", "tool": TOOL, "arguments": {"domain": "a.com", "country": "fr"}}]}
    await Orchestrator(prowl, llm, runs_root=tmp_path / "runs").run("notsent-lookup", BRIEF, run_id="spelling")
    assert [c["arguments"]["country"] for c in prowl.tool_calls] == ["FR"]
    assert tool_limits.canonical("tiktok_ads_library", {"country": "gb"}) == {"country": "GB"}
    assert tool_limits.canonical("meta_ad_library", {"country": "gb"}) == {"country": "gb"}


def test_the_evidence_only_report_carries_the_coverage_note(tmp_path):
    from research_agent.agent.writer import ledger_only_report
    from research_agent.evidence.ledger import Ledger
    from research_agent.runbook import get_runbook

    outcome = ledger_only_report(get_runbook("ads-creative-research"), Ledger(tmp_path / "ledger.json"), "budget",
                                 tool_limits.coverage_notes(["tiktok_ads_library"]))
    assert "European markets only" in outcome.report_md


class _StubObservedProwl:
    """The service's Prowl client without a network: records what it would send."""

    sent: list = []

    def __init__(self, *args, **kwargs):
        pass

    def observe(self, store, job):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def call_tool(self, name, arguments, idempotency_key=None):
        _StubObservedProwl.sent.append((name, dict(arguments)))
        return {"ads": []}


@pytest.fixture
def stub_service(tmp_path, monkeypatch):
    from research_agent.service import runtime as service_runtime
    from research_agent.service.store import Store

    monkeypatch.setenv("PROWL_API_KEY", "test-key")
    monkeypatch.setattr(service_runtime, "ObservedProwl", _StubObservedProwl)
    _StubObservedProwl.sent = []
    return service_runtime.Runtime(Store(tmp_path))


async def test_a_direct_call_is_sent_in_the_providers_spelling_and_returns_its_coverage(stub_service):
    rt = stub_service
    job = rt.create({"kind": "tool", "tool": "tiktok_ads_library", "params": {"query": "x", "country": "gb"}}, "spell-1")
    rt.store.decide(job["id"], job["proposal"]["digest"], True)
    await rt.execute(job["id"])
    assert _StubObservedProwl.sent == [("tiktok_ads_library", {"query": "x", "country": "GB"})]
    done = rt.store.job(job["id"])
    assert done["status"] == "completed"
    assert done["result"]["output"]["coverage"] == tool_limits.statements(["tiktok_ads_library"])
    assert "European markets only" in done["result"]["output"]["coverage"][0]
    assert "say so" not in done["result"]["output"]["coverage"][0]  # a fact for a person, not the writer's order
    assert any(n["claim"] == "Source coverage" for n in done["result"]["notVerified"])


async def test_a_job_created_before_a_limit_is_refused_at_dispatch_with_its_reason(stub_service, monkeypatch):
    rt = stub_service
    known = tool_limits.LIMITS["tiktok_ads_library"]
    monkeypatch.setitem(tool_limits.LIMITS, "tiktok_ads_library", {})  # the limit is not known yet
    job = rt.create({"kind": "tool", "tool": "tiktok_ads_library", "params": {"query": "x", "country": "US"}}, "old-1")
    tool_limits.LIMITS["tiktok_ads_library"] = known  # the upgrade: the limit is known when the job is sent
    rt.store.decide(job["id"], job["proposal"]["digest"], True)
    await rt.execute(job["id"])
    done = rt.store.job(job["id"])
    assert _StubObservedProwl.sent == []
    assert done["status"] == "failed"
    assert done["error"]["code"] == "request-rejected" and "known provider limit" in done["error"]["message"]


async def test_an_outcome_unknown_resend_sends_what_the_earlier_attempt_sent(lookup_runbook, tmp_path, monkeypatch):
    """The re-send reuses its key and the server matches key with params: a value first sent as
    'gb' (before its limit was known) is re-sent as 'gb', never as the new spelling 'GB'."""
    from mcp.shared.exceptions import McpError
    from mcp.types import CallToolResult, ErrorData

    from research_agent.prowl_client import ProwlClient

    class TimeoutOnce(ProwlClient):
        def __init__(self):
            super().__init__(api_key="test", mcp_url="http://unused.invalid")
            self.sent, self.calls = [], 0
            self.tool_prices = {TOOL: 0.1}

        async def list_tools(self):
            return [TOOL, "dataforseo_bl_summary"]

        async def tool_info(self, name):
            return {"name": name}

        async def _rpc(self, name, arguments, retry=True):
            self.calls += 1
            self.sent.append((arguments["idempotency_key"], dict(arguments["params"])))
            if self.calls == 1:
                raise McpError(ErrorData(code=408, message="Timed out while waiting for response"))
            return CallToolResult(content=[], structuredContent={"rows": [{"value": 1}]})

    runs = tmp_path / "runs"
    client = TimeoutOnce()
    llm = FakeLLM()
    llm.plan_payload = {"plan": [{"step": "s", "tool": TOOL, "arguments": {"domain": "a.com", "country": "gb"}}]}
    first = await Orchestrator(client, llm, runs_root=runs).run("notsent-lookup", BRIEF, run_id="resend")
    assert _step(_checkpoint(runs, "resend"), "s")["state"] == "outcome_unknown" and first.status == "partial"
    limit = tool_limits.ArgumentLimit(allowed=frozenset({"all", "GB"}), note="n", source="test")
    monkeypatch.setitem(tool_limits.LIMITS, TOOL, {"country": limit})  # the upgrade lands between the two
    await Orchestrator(client, llm, runs_root=runs).run("notsent-lookup", BRIEF, run_id="resend")
    assert client.sent[0] == client.sent[1]  # same key, same params: the server can replay


@pytest.mark.parametrize("value", ["US", "PLACEHOLDER_FROM_STEP_1"])
async def test_a_dispatched_step_is_resent_not_relabelled_by_a_rule_learned_since(lookup_runbook, tmp_path,
                                                                                   monkeypatch, value):
    """An outcome_unknown step was sent: a limit or template rule that lands before the resume
    re-sends it under its key rather than calling it "not sent"."""
    from mcp.shared.exceptions import McpError
    from mcp.types import CallToolResult, ErrorData

    from research_agent.prowl_client import ProwlClient

    class TimeoutOnce(ProwlClient):
        def __init__(self):
            super().__init__(api_key="test", mcp_url="http://unused.invalid")
            self.sent, self.calls = [], 0
            self.tool_prices = {TOOL: 0.1}

        async def list_tools(self):
            return [TOOL, "dataforseo_bl_summary"]

        async def tool_info(self, name):
            return {"name": name}

        async def _rpc(self, name, arguments, retry=True):
            self.calls += 1
            self.sent.append((arguments["idempotency_key"], dict(arguments["params"])))
            if self.calls == 1:
                raise McpError(ErrorData(code=408, message="Timed out while waiting for response"))
            return CallToolResult(content=[], structuredContent={"rows": [{"value": 1}]})

    known = bindings._TEMPLATE_RES
    monkeypatch.setattr(bindings, "_TEMPLATE_RES", ())  # the template rule is not known yet
    runs = tmp_path / "runs"
    client = TimeoutOnce()
    llm = FakeLLM()
    llm.plan_payload = {"plan": [{"step": "s", "tool": TOOL, "arguments": {"domain": "a.com", "country": value}}]}
    await Orchestrator(client, llm, runs_root=runs).run("notsent-lookup", BRIEF, run_id="relabel")
    bindings._TEMPLATE_RES = known  # the upgrade lands between the two
    limit = tool_limits.ArgumentLimit(allowed=frozenset({"all", "GB"}), note="n", source="test")
    monkeypatch.setitem(tool_limits.LIMITS, TOOL, {"country": limit})
    await Orchestrator(client, llm, runs_root=runs).run("notsent-lookup", BRIEF, run_id="relabel")
    assert len(client.sent) == 2 and client.sent[0] == client.sent[1]
    step = _step(_checkpoint(runs, "relabel"), "s")
    assert step["state"] == "completed" and "not sent" not in str(step["reason"])
