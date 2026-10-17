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


async def _service_research_job(tmp_path, monkeypatch, provider, *, env_cap=None, prefill=0):
    import asyncio

    import research_agent.service.runtime as runtime_mod
    from research_agent.evidence.store import ArtifactStore
    from research_agent.service.runtime import Runtime

    monkeypatch.setenv("PROWL_API_KEY", "test-not-a-key")
    monkeypatch.setenv("RESEARCH_LLM_API_KEY", "test-not-a-key")
    monkeypatch.setenv("RESEARCH_NO_SUBAGENTS", "1")
    if env_cap is None:
        monkeypatch.delenv("RESEARCH_MAX_LLM_USD", raising=False)
    else:
        monkeypatch.setenv("RESEARCH_MAX_LLM_USD", str(env_cap))

    async def no_sleep(_):
        return None

    monkeypatch.setattr("research_agent.llm.asyncio.sleep", no_sleep)

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
        for _ in range(prefill):
            store.finish_call(store.start_call(job["id"], "tool", "prefill", {}), status="completed",
                              costUsd=0.0, costBasis="provider")
        rt.decide(job["id"], job["proposal"]["digest"], True)
        await asyncio.gather(*list(rt.tasks.values()))
        done = store.job(job["id"])
        checkpoint = ArtifactStore(tmp_path / "runs" / job["id"]).load_checkpoint()
        return done, store.calls(job["id"]), checkpoint
    finally:
        await rt.close()
        store.db.close()


def _assert_journal_matches_ledger(journal, attempts):
    for kind in ("tool", "llm"):
        rows = [c for c in journal if c["kind"] == kind and c["name"] != "prefill"]
        ledger = [a for a in attempts if a.kind == kind]
        assert len(rows) == len(ledger), kind
        # same cost wherever the provider reported one; an unbilled HTTP error
        # is unknown (null) in the journal and 0 in the run ledger
        assert sum(c["costUsd"] or 0 for c in rows) == pytest.approx(sum(a.spend_usd for a in ledger)), kind


async def test_a_service_research_job_journals_exactly_the_attempts_its_run_ledger_counts(
        tmp_path, monkeypatch, patched_runbooks):
    """The call journal (dashboard, usage report) and the run's attempt ledger
    (budgets, resume) are written at the same boundary — each HTTP attempt to
    the LLM and each paid dispatch — so they agree call for call."""
    from test_llm_budget import Provider

    done, journal, checkpoint = await _service_research_job(tmp_path, monkeypatch, Provider(cost=0.02, plan_steps=2))
    assert done["status"] == "completed", done.get("error")
    assert done["result"]["outcome"] == "succeeded"
    _assert_journal_matches_ledger(journal, checkpoint.attempts)


async def test_journal_and_ledger_agree_across_a_429(tmp_path, monkeypatch, patched_runbooks):
    from test_llm_budget import Provider

    provider = Provider(cost=0.02, plan_steps=1, script=[(429, {"error": "rate"})])
    done, journal, checkpoint = await _service_research_job(tmp_path, monkeypatch, provider)
    assert done["status"] == "completed", done.get("error")
    assert any(a.outcome == "http_error" and a.spend_usd == 0 for a in checkpoint.attempts)
    _assert_journal_matches_ledger(journal, checkpoint.attempts)


async def test_the_service_call_limit_refuses_before_anything_is_recorded(tmp_path, monkeypatch, patched_runbooks):
    from test_llm_budget import Provider

    done, journal, checkpoint = await _service_research_job(tmp_path, monkeypatch, Provider(cost=0.02), prefill=256)
    assert done["status"] == "failed"
    assert [a for a in checkpoint.attempts if a.kind == "llm"] == []  # nothing sent, nothing spent
    assert len(journal) == 256


async def test_a_service_job_stopped_by_the_llm_cap_reports_partial(tmp_path, monkeypatch, patched_runbooks):
    from test_llm_budget import Provider

    done, journal, checkpoint = await _service_research_job(
        tmp_path, monkeypatch, Provider(cost=0.4, plan_steps=2), env_cap=1.0)
    assert done["status"] == "completed", done.get("error")
    assert checkpoint.terminal_code == "budget_llm"
    assert done["result"]["outcome"] == "partial" and "budget_llm" in done["result"]["done"][0]["statement"]


def test_configuring_the_event_log_twice_keeps_one_handler(tmp_path):
    from logging.handlers import RotatingFileHandler

    from research_agent.service.cli import configure_logging

    package = logging.getLogger("research_agent")
    before = list(package.handlers), package.level, package.propagate
    try:
        configure_logging(tmp_path / "logs")
        configure_logging(tmp_path / "logs")
        assert sum(isinstance(h, RotatingFileHandler) for h in package.handlers) == 1
    finally:
        for handler in package.handlers:
            if handler not in before[0]:
                handler.close()
        package.handlers[:] = before[0]
        package.setLevel(before[1])
        package.propagate = before[2]


@pytest.mark.parametrize("body,gaps", [
    ("Use `serp_bing` as a fallback for organic data.", ["serp_bing"]),
    ("There is no fallback for `moz_da`.", []),
    ("If the call fails, e.g. on timeout, use `google_search`.", ["google_search"]),
    ("Fall-back: `serp_bing`.", ["serp_bing"]),
    ("Primary `moz_da`. Then something else.", []),
])
def test_failover_sentences(body, gaps):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "validate_runbooks", Path(__file__).resolve().parent.parent / "scripts" / "validate_runbooks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.failover_gaps(body, [], ["serp_bing", "moz_da", "google_search"]) == gaps


async def test_a_failed_service_job_is_resumed_without_paying_again(tmp_path, monkeypatch, patched_runbooks):
    """B-039: research.run with resumeJobId continues the ended job's run: the
    paid tool step is not dispatched again; only the writer runs."""
    import asyncio

    import research_agent.service.runtime as runtime_mod
    from research_agent.evidence.store import ArtifactStore
    from research_agent.service.runtime import Runtime
    from test_llm_budget import Provider

    monkeypatch.setenv("PROWL_API_KEY", "test-not-a-key")
    monkeypatch.setenv("RESEARCH_LLM_API_KEY", "test-not-a-key")
    monkeypatch.setenv("RESEARCH_NO_SUBAGENTS", "1")
    monkeypatch.delenv("RESEARCH_MAX_LLM_USD", raising=False)
    dispatched = []
    healthy = Provider(cost=0.01, plan_steps=1)
    state = {"writer_down": True}

    def provider(request):
        body = json.loads(request.content)
        if state["writer_down"] and "response_format" not in body:
            return httpx.Response(400, json={"error": "writer unavailable"})
        return healthy(request)

    class Session:
        async def call_tool(self, name, arguments, **kwargs):
            if name == "prowl_list_tools":
                body = {"tools": ["spyfu_get_domain_stats", "dataforseo_bl_summary"]}
            else:
                if name == "prowl_call_tool":
                    dispatched.append(arguments)
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
        request = {"kind": "research", "runbook": "mini-teardown", "inputs": {"competitors": ["example.com"]}}
        first = rt.create(dict(request, max_llm_usd=2.0), "first")
        rt.decide(first["id"], first["proposal"]["digest"], True)
        await asyncio.gather(*list(rt.tasks.values()))
        assert store.job(first["id"])["status"] == "failed"
        assert len(dispatched) == 1
        with pytest.raises(ValueError, match="another runbook|names no job"):
            rt.create(dict(request, runbook="mini-teardown", resumeJobId="nope"), "bad")
        with pytest.raises(ValueError, match="own inputs"):
            rt.create(dict(request, inputs={"competitors": ["other.example"]}, resumeJobId=first["id"]), "other")
        # the writer is still down: the resume fails too, and a resume of THAT resume continues the same run
        second = rt.create(dict(request, resumeJobId=first["id"]), "resume")
        assert second["status"] == "input_required"  # a resume can spend: the operator still decides
        rt.decide(second["id"], second["proposal"]["digest"], True)
        await asyncio.gather(*list(rt.tasks.values()))
        assert store.job(second["id"])["status"] == "failed"
        state["writer_down"] = False
        third = rt.create(dict(request, resumeJobId=second["id"]), "resume-2")
        with pytest.raises(ValueError, match="already being continued"):
            rt.create(dict(request, resumeJobId=first["id"]), "concurrent")
        rt.decide(third["id"], third["proposal"]["digest"], True)
        await asyncio.gather(*list(rt.tasks.values()))
        done = store.job(third["id"])
        assert done["status"] == "completed", done.get("error")
        assert len(dispatched) == 1  # the paid step was sent once across the whole chain
        assert done["runDir"] == first["id"] == store.job(second["id"])["runDir"]
        assert not (tmp_path / "runs" / second["id"]).exists() and not (tmp_path / "runs" / third["id"]).exists()
        checkpoint = ArtifactStore(tmp_path / "runs" / first["id"]).load_checkpoint()
        assert checkpoint.status == "complete" and checkpoint.llm_cap_usd == 2.0
        with pytest.raises(ValueError, match="nothing is left to continue"):
            rt.create(dict(request, resumeJobId=third["id"]), "again")
        from research_agent.service.protocol import artifact
        assert artifact(store, third["id"], "report.md")["content"].startswith("# Report")
        with pytest.raises(ValueError, match="max_llm_usd"):
            rt.create(dict(request, max_llm_usd=0), "zero")
    finally:
        await rt.close()
        store.db.close()


def test_a_resume_respects_the_principal_and_the_operators_rejection(tmp_path, monkeypatch, patched_runbooks):
    from research_agent.service.delegation import Refused
    from research_agent.service.runtime import Runtime

    monkeypatch.setenv("PROWL_API_KEY", "test-not-a-key")
    monkeypatch.setenv("RESEARCH_LLM_API_KEY", "test-not-a-key")
    store = Store(tmp_path)
    rt = Runtime(store)
    alice = {"principal": "urn:person:a", "caller": "caller-a.default", "chain": [], "kid": "k1", "tier": "T2"}
    bob = dict(alice, caller="caller-b.default")
    request = {"kind": "research", "runbook": "mini-teardown", "inputs": {"competitors": ["example.com"]}}
    try:
        job = rt.create(request, "same-key", delegation=alice)
        # the idempotency key is per principal: another caller's same key is another job
        assert rt.create(request, "same-key", delegation=bob)["id"] != job["id"]
        assert rt.create(request, "same-key", delegation=alice)["id"] == job["id"]
        rt.decide(job["id"], job["proposal"]["digest"], False)
        assert store.job(job["id"])["phase"] == "rejected"
        with pytest.raises(Refused) as refused:
            rt.create(dict(request, resumeJobId=job["id"]), "steal", delegation=bob)
        assert refused.value.verdict["code"] == "scope-not-granted"
        with pytest.raises(ValueError, match="rejected by the operator"):
            rt.create(dict(request, resumeJobId=job["id"]), "again", delegation=alice)
    finally:
        store.db.close()


def test_a_resume_replayed_with_the_same_key_returns_the_same_job(tmp_path, monkeypatch, patched_runbooks):
    """W6 seam finding: an agent retrying research.run+resumeJobId after a lost
    answer gets its job back, not 'already being continued'."""
    from research_agent.service.runtime import Runtime, run_dir_name

    monkeypatch.setenv("PROWL_API_KEY", "test-not-a-key")
    monkeypatch.setenv("RESEARCH_LLM_API_KEY", "test-not-a-key")
    store = Store(tmp_path)
    rt = Runtime(store)
    alice = {"principal": "urn:person:a", "caller": "caller-a.default", "chain": [], "kid": "k1", "tier": "T2"}
    request = {"kind": "research", "runbook": "mini-teardown", "inputs": {"competitors": ["example.com"]}}
    try:
        first = rt.create(request, "first", delegation=alice)
        store.transition(first["id"], "failed", "failed", error={"code": "execution-failed", "message": "x"})
        resume = rt.create(dict(request, resumeJobId=first["id"]), "resume-key", delegation=alice)
        again = rt.create(dict(request, resumeJobId=first["id"]), "resume-key", delegation=alice)
        assert again["id"] == resume["id"]
        # an operator resume of alice's job stays alice's
        store.transition(resume["id"], "failed", "failed", error={"code": "execution-failed", "message": "x"})
        operator = rt.create(dict(request, resumeJobId=resume["id"]), "op-key")
        assert operator["delegation"]["caller"] == "caller-a.default"
        # a pre-runDir resume body still maps to the run it continues
        assert run_dir_name({"id": "pr-b", "request": {"resumeJobId": "pr-a"}}) == "pr-a"
    finally:
        store.db.close()
