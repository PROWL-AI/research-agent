"""B-100: a caller's daily allowance approves a paid job that fits it; above it the job waits for the operator.

The operator's word (agents database intake in-20261112-996c34): every key that reads or orders carries a daily
ceiling of at least 10 USD per UTC day. Delegation rules of 2026-11-05 and 2026-11-07: an approval inside a task is
the agent's. So a job an agent creates within its ceiling starts without a person; the dashboard's requests and the
jobs above the ceiling wait as before.
"""
from __future__ import annotations

import pytest

from research_agent.service import allowance
from research_agent.service.clients import DAILY_FLOOR_USD, FileClients
from research_agent.service.runtime import Runtime
from research_agent.service.store import Store

RESEARCH = {"kind": "research", "runbook": "market-pulse", "inputs": {"market": "eSIM"}}
TOOL = {"kind": "tool", "tool": "google_news", "params": {"q": "esim"}}


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("PROWL_API_KEY", "p")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    monkeypatch.delenv("RESEARCH_MAX_LLM_USD", raising=False)
    rt = Runtime(Store(tmp_path))
    started = []

    async def nothing(job_id):  # the run itself is not this test's subject
        started.append(job_id)

    monkeypatch.setattr(rt, "execute", nothing)
    rt.started = started
    return rt


def client(name, daily=None):
    d = {"principal": "client:" + name, "caller": "client:" + name, "chain": [], "kid": None, "tier": "client"}
    return d | ({"dailyUsd": daily} if daily is not None else {})


def test_worst_case_of_a_research_job_is_its_tool_budget_and_llm_cap():
    # market-pulse: max_usd 1.5; no runbook LLM cap, so the default 5.0
    assert allowance.worst_case_usd(RESEARCH) == pytest.approx(6.5)
    assert allowance.worst_case_usd(RESEARCH | {"max_llm_usd": 2.0}) == pytest.approx(3.5)
    assert allowance.worst_case_usd(TOOL) == allowance.TOOL_JOB_WORST_USD
    assert allowance.worst_case_usd({"kind": "tutorial"}) == 0.0
    assert allowance.worst_case_usd({"kind": "research", "runbook": "no-such"}) > 1000


async def test_an_agent_job_within_its_allowance_starts_without_a_person(runtime):
    job = runtime.create(RESEARCH, "k1", via="mcp")
    assert job["status"] == "working" and job["phase"] == "queued"
    assert job["decision"]["by"] == "allowance" and job["decision"]["approved"] is True
    assert job["decision"]["principal"] == "agent" and job["decision"]["ceilingUsd"] == 10.0
    assert runtime.store.events(after=0, limit=50)["events"][-1]["text"].startswith("Запуск разрешён дневным лимитом")


async def test_the_second_job_that_would_cross_the_ceiling_waits(runtime):
    first = runtime.create(RESEARCH, "k1", via="mcp")
    second = runtime.create(RESEARCH | {"inputs": {"market": "VPN"}}, "k2", via="mcp")
    assert first["status"] == "working"
    assert second["status"] == "input_required", "6.5 + 6.5 is above the 10 USD day"
    # A cheaper job still fits what is left.
    assert runtime.create(TOOL, "k3", via="mcp")["status"] == "working"


async def test_a_finished_job_counts_what_it_really_cost(runtime):
    first = runtime.create(RESEARCH, "k1", via="mcp")
    call = runtime.store.start_call(first["id"], "tool", "google_news", {})
    runtime.store.finish_call(call, status="completed", costUsd=0.4)
    runtime.store.transition(first["id"], "completed", "completed")
    assert allowance.spent_today(runtime.store, "agent") == pytest.approx(0.4)
    assert runtime.create(RESEARCH | {"inputs": {"market": "VPN"}}, "k2", via="mcp")["status"] == "working"


async def test_an_unpriced_call_keeps_the_worst_case(runtime):
    first = runtime.create(RESEARCH, "k1", via="mcp")
    call = runtime.store.start_call(first["id"], "tool", "google_news", {})
    runtime.store.finish_call(call, status="completed", costUsd=None)
    runtime.store.transition(first["id"], "completed", "completed")
    assert allowance.spent_today(runtime.store, "agent") == pytest.approx(6.5)


async def test_the_dashboards_requests_still_wait_for_the_operator(runtime):
    assert runtime.create(RESEARCH, "k1", via="dashboard")["status"] == "input_required"


async def test_zero_turns_the_local_allowance_off(runtime):
    config = runtime.store.config()
    runtime.store.configure(config["revision"], {k: v for k, v in config.items() if k != "revision"} | {"agent_daily_usd": 0.0})
    assert runtime.create(TOOL, "k1", via="mcp")["status"] == "input_required"


async def test_the_free_tutorial_never_waits(runtime):
    job = runtime.create({"kind": "tutorial"}, "k1", via="mcp")
    assert job["status"] == "working" and job["decision"]["reason"] == "free"


async def test_each_cloud_client_has_its_own_day(runtime):
    anna = runtime.create(RESEARCH, "k1", delegation=client("anna"))
    boris = runtime.create(RESEARCH, "k1", delegation=client("boris"))
    assert anna["status"] == boris["status"] == "working"
    assert runtime.create(RESEARCH | {"inputs": {"market": "VPN"}}, "k2", delegation=client("anna"))["status"] == "input_required"
    # A client with a higher ceiling fits the second run.
    rich = client("rich", 20.0)
    runtime.create(RESEARCH, "k1", delegation=rich)
    assert runtime.create(RESEARCH | {"inputs": {"market": "VPN"}}, "k2", delegation=rich)["status"] == "working"


async def test_a_client_ceiling_below_the_floor_counts_as_the_floor(runtime):
    job = runtime.create(TOOL, "k1", delegation=client("low", 1.0))
    assert job["decision"]["ceilingUsd"] == DAILY_FLOOR_USD


async def test_the_operators_approval_of_a_waiting_job_counts_against_the_callers_day(runtime):
    runtime.create(RESEARCH, "k1", via="mcp")
    waiting = runtime.create(RESEARCH | {"inputs": {"market": "VPN"}}, "k2", via="mcp")
    approved = runtime.decide(waiting["id"], waiting["proposal"]["digest"], True)
    assert approved["decision"]["by"] == "operator"
    assert allowance.spent_today(runtime.store, "agent") == pytest.approx(13.0)


def test_client_keys_carry_a_daily_ceiling_of_at_least_ten(tmp_path):
    clients = FileClients(tmp_path / "clients.json")
    key = clients.add("anna", ["read"])
    assert clients.verify(key)["dailyUsd"] == 10.0
    with pytest.raises(ValueError, match="at least 10"):
        clients.add("cheap", ["read"], daily_usd=5)
    clients.limit("anna", 25)
    assert clients.verify(key)["dailyUsd"] == 25.0
    assert clients.list()[0]["dailyUsd"] == 25.0
    with pytest.raises(ValueError):
        clients.limit("anna", 9.99)


def test_a_key_stored_before_the_ceiling_reads_as_the_floor(tmp_path):
    import json

    path = tmp_path / "clients.json"
    clients = FileClients(path)
    key = clients.add("old", ["read"])
    data = json.loads(path.read_text())
    del data["old"]["dailyUsd"]
    path.write_text(json.dumps(data))
    assert clients.verify(key)["dailyUsd"] == 10.0
