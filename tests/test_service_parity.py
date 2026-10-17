"""Wave 4 (N-SVC): the service runs the same core as the CLI and stdio MCP.

B-003 one LLM transport, B-004 metadata calls keep the core's reconnect,
B-005 the envelope outcome follows the run, B-029 failover allowlist warning,
B-035 the service's events reach a rotating log file.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from mcp.types import CallToolResult, TextContent

from research_agent.service.runtime import ObservedLLM, ObservedProwl, outcome_for
from research_agent.service.store import Store


def _completion(content="ok", cost=0.01):
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "cost": cost}}


async def test_service_llm_retries_a_429_like_the_core_and_journals_each_attempt(tmp_path, monkeypatch):
    store = Store(tmp_path)
    job = store.create({"kind": "research"}, "llm-429")[0]
    job["traceparent"] = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
    seen = []

    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, json={"error": "rate"})
        return httpx.Response(200, json=_completion())

    async def no_sleep(_):
        return None

    monkeypatch.setattr("research_agent.llm.asyncio.sleep", no_sleep)
    llm = ObservedLLM("https://llm.invalid", "fake", "cheap", "strong").observe(store, job)
    await llm._client.aclose()
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await llm.complete([{"role": "user", "content": "x"}], max_tokens=4000) == "ok"
    await llm.aclose()
    calls = store.calls(job["id"])
    assert [c["status"] for c in calls] == ["failed", "completed"]  # one journal row per attempt
    assert calls[1]["costUsd"] == 0.01
    assert all("traceparent" in r.headers for r in seen)
    # the core's max_tokens-scaled read timeout reached the transport
    assert seen[-1].extensions["timeout"]["read"] == 200.0


async def test_service_metadata_calls_reconnect_but_a_paid_call_is_sent_once(tmp_path, monkeypatch):
    store = Store(tmp_path)
    job = store.create({"kind": "tool"}, "reconnect")[0]
    prowl = ObservedProwl("fake", "https://example.invalid").observe(store, job)
    attempts = {"meta": 0, "paid": 0}

    class Session:
        async def call_tool(self, name, arguments, **kwargs):
            key = "paid" if name == "prowl_call_tool" else "meta"
            attempts[key] += 1
            if attempts[key] == 1:
                raise httpx.ConnectError("dropped")
            return CallToolResult(content=[TextContent(type="text", text=json.dumps({"tools": []}))])

    async def reconnect():
        prowl._session = Session()

    async def no_sleep(_):
        return None

    monkeypatch.setattr("research_agent.prowl_client.asyncio.sleep", no_sleep)
    prowl._session = Session()
    prowl._reconnect = reconnect
    await prowl._rpc("prowl_list_tools", {})  # metadata: dropped once, reconnected, answered
    assert attempts["meta"] == 2
    with pytest.raises(Exception):
        await prowl.call_tool("spyfu_get_domain_stats", {}, idempotency_key="k")
    assert attempts["paid"] == 1  # never re-sent: a lost reply is not permission to pay again


@pytest.mark.parametrize("output,expected", [
    ({"research": {"status": "complete", "terminal_code": "completed"}}, "succeeded"),
    ({"research": {"status": "partial", "terminal_code": "budget_llm"}}, "partial"),
    ({"data": {}, "quality": "provider response"}, "succeeded"),
    ({"tutorial": True}, "succeeded"),
])
def test_envelope_outcome_follows_the_run(output, expected):
    outcome, statement = outcome_for(output)
    assert outcome == expected
    if expected == "partial":
        assert "budget_llm" in statement


def test_failover_tools_missing_from_the_allowlist_are_reported():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "validate_runbooks", Path(__file__).resolve().parent.parent / "scripts" / "validate_runbooks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    body = ("1. **Brands** — `foreplay_discovery_ads` (fallback on failure: `foreplay_discovery_brands`\n"
            "   fuzzy name search, then `meta_ad_library_page_search`).\n\n"
            "2. **Other** — `spyfu_get_domain_stats`.\n")
    catalog = ["foreplay_discovery_ads", "foreplay_discovery_brands", "meta_ad_library_page_search",
               "spyfu_get_domain_stats"]
    gaps = module.failover_gaps(body, ["foreplay_discovery_ads", "foreplay_discovery_brands"], catalog)
    assert gaps == ["meta_ad_library_page_search"]
    assert module.failover_gaps(body, catalog, catalog) == []


def test_service_events_reach_a_rotating_log_file(tmp_path):
    from logging.handlers import RotatingFileHandler

    from research_agent.events import emit
    from research_agent.service.cli import EVENT_LOG_BACKUPS, EVENT_LOG_BYTES, configure_logging

    package = logging.getLogger("research_agent")
    before = list(package.handlers), package.level, package.propagate
    try:
        path = configure_logging(tmp_path / "logs")
        emit(logging.getLogger("research_agent.evidence.ledger"), "claim.verified", claim_id="C1", method="span")
        for handler in package.handlers:
            handler.flush()
        assert "event=claim.verified claim_id=C1 method=span" in path.read_text()
        rotating = [h for h in package.handlers if isinstance(h, RotatingFileHandler)]
        assert rotating and rotating[-1].maxBytes == EVENT_LOG_BYTES and rotating[-1].backupCount == EVENT_LOG_BACKUPS
    finally:
        for handler in package.handlers:
            if handler not in before[0]:
                handler.close()
        package.handlers[:] = before[0]
        package.setLevel(before[1])
        package.propagate = before[2]


async def test_a_service_research_job_journals_exactly_the_attempts_its_run_ledger_counts(
        tmp_path, monkeypatch, patched_runbooks):
    """The call journal (dashboard, usage report) and the run's attempt ledger
    (budgets, resume) are written at the same boundary — each HTTP attempt to
    the LLM and each paid dispatch — so they must agree call for call."""
    import asyncio

    import research_agent.service.runtime as runtime_mod
    from research_agent.evidence.store import ArtifactStore
    from research_agent.service.runtime import Runtime
    from test_llm_budget import Provider

    monkeypatch.setenv("PROWL_API_KEY", "test-not-a-key")
    monkeypatch.setenv("RESEARCH_LLM_API_KEY", "test-not-a-key")
    monkeypatch.setenv("RESEARCH_NO_SUBAGENTS", "1")
    provider = Provider(cost=0.02, plan_steps=2)

    class Session:
        async def call_tool(self, name, arguments, **kwargs):
            if name == "prowl_list_tools":
                body = {"tools": ["spyfu_get_domain_stats", "dataforseo_bl_summary"]}
            else:
                body = {"success": True, "data": {"visits": 42}, "billing": {"actual_cost_usd": 0.05}}
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(body))])

    class TestProwl(ObservedProwl):
        async def __aenter__(self):
            self._session = Session()
            return self

        async def __aexit__(self, *exc):
            return None

    class TestLLM(ObservedLLM):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._client = httpx.AsyncClient(transport=httpx.MockTransport(provider))

    monkeypatch.setattr(runtime_mod, "ObservedProwl", TestProwl)
    monkeypatch.setattr(runtime_mod, "ObservedLLM", TestLLM)
    store = Store(tmp_path)
    rt = Runtime(store)
    try:
        job = rt.create({"kind": "research", "runbook": "mini-teardown",
                         "inputs": {"competitors": ["example.com"]}}, "parity")
        rt.decide(job["id"], job["proposal"]["digest"], True)
        await asyncio.gather(*list(rt.tasks.values()))
        done = store.job(job["id"])
        assert done["status"] == "completed", done.get("error")
        assert done["result"]["outcome"] == "succeeded"
        journal = store.calls(job["id"])
        attempts = ArtifactStore(tmp_path / "runs" / job["id"]).load_checkpoint().attempts
        for kind in ("tool", "llm"):
            rows = [c for c in journal if c["kind"] == kind]
            ledger = [a for a in attempts if a.kind == kind]
            assert len(rows) == len(ledger) > 0, kind
            assert sum(c["costUsd"] for c in rows) == pytest.approx(sum(a.spend_usd for a in ledger)), kind
    finally:
        await rt.close()
        store.db.close()
