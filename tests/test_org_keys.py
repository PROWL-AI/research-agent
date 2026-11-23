"""B-160: one organization key per organization, its monthly ceiling, and the organization's report memory.

The operator's word of 2026-11-23 (relayed by the Fabric CEO, board request 39a22ae6): a key of its own for every
organization, a limit of 1000, its people share one memory of the reports they run, a report one of them ran is
seen and taken by the others so nobody runs it twice, and organizations stay apart.
"""
from __future__ import annotations

import httpx
import pytest

from research_agent.service import allowance, reports
from research_agent.service.app import CloudSettings, create_app
from research_agent.service.clients import ORG_MONTHLY_DEFAULT_USD, FileClients
from research_agent.service.delegation import owned_by
from research_agent.service.runtime import Runtime
from research_agent.service.store import Store

#: every test here exercises the allowance itself (conftest turns it off elsewhere)
pytestmark = pytest.mark.allowance

ORIGIN = "https://research.example.test"
RESEARCH = {"kind": "research", "runbook": "market-pulse", "inputs": {"market": "eSIM"}}


def org(name, key="org-" + "x", monthly=ORG_MONTHLY_DEFAULT_USD):
    return {"principal": "org:" + name, "caller": "client:" + key, "chain": [], "kid": None, "tier": "client",
            "keyClass": "organization", "org": name, "monthlyUsd": monthly}


# --- the key ---------------------------------------------------------------------------------------------------


def test_an_organization_key_carries_its_org_and_a_monthly_ceiling_and_no_daily_one(tmp_path):
    clients = FileClients(tmp_path / "clients.json")
    key = clients.add("org-appvillis", ["read", "research.run", "tools.call"], key_class="organization", org="appvillis")
    seen = clients.verify(key)
    assert seen["keyClass"] == "organization" and seen["org"] == "appvillis"
    assert seen["monthlyUsd"] == 1000.0 and seen["dailyUsd"] is None
    listed = {c["name"]: c for c in clients.list()}["org-appvillis"]
    assert listed["org"] == "appvillis" and listed["monthlyUsd"] == 1000.0 and listed["dailyUsd"] is None


@pytest.mark.parametrize("kwargs, message", [
    ({"key_class": "organization"}, "organization:"),
    ({"key_class": "organization", "org": "Bad Org"}, "organization:"),
    ({"key_class": "organization", "org": "a", "daily_usd": 20}, "no daily ceiling"),
    ({"key_class": "organization", "org": "a", "monthly_usd": 5}, "monthly ceiling"),
    ({"key_class": "organization", "org": "a", "monthly_usd": 4001}, "monthly ceiling"),
    ({"key_class": "automated", "org": "a"}, "belong to an organization key"),
])
def test_an_organization_key_is_refused_without_its_fields(tmp_path, kwargs, message):
    with pytest.raises(ValueError, match=message):
        FileClients(tmp_path / "clients.json").add("k", ["read"], **kwargs)


def test_the_monthly_ceiling_can_be_changed_only_on_an_organization_key(tmp_path):
    clients = FileClients(tmp_path / "clients.json")
    clients.add("org-pc", ["read"], key_class="organization", org="passioncode")
    clients.add("pipeline", ["read"])
    clients.monthly("org-pc", 1500)
    assert {c["name"]: c for c in clients.list()}["org-pc"]["monthlyUsd"] == 1500.0
    with pytest.raises(ValueError, match="not an organization key"):
        clients.monthly("pipeline", 100)
    with pytest.raises(ValueError, match="no daily ceiling"):
        clients.limit("org-pc", 20)


def test_a_desk_never_issues_an_organization_key(tmp_path):
    clients = FileClients(tmp_path / "clients.json")
    clients.add_desk("ania", grants=["read"], max_daily_usd=10)
    with pytest.raises(ValueError, match="operator's tool only"):
        clients.desk_issue("ania", "org-sneaky", ["read"], key_class="organization")


# --- whose jobs ------------------------------------------------------------------------------------------------


def test_an_organizations_jobs_are_shared_by_its_keys_and_closed_to_others():
    job = {"delegation": org("appvillis", "org-appvillis")}
    assert owned_by(job, org("appvillis", "org-appvillis"))
    assert owned_by(job, org("appvillis", "org-appvillis-2"))  # a second key of the same organization
    assert not owned_by(job, org("passioncode", "org-passioncode"))
    personal = {"principal": "client:personal-key", "caller": "client:personal-key", "tier": "client"}
    assert not owned_by(job, personal)
    assert not owned_by({"delegation": personal}, org("appvillis", "org-appvillis"))


# --- the monthly allowance -------------------------------------------------------------------------------------


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("PROWL_API_KEY", "p")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    monkeypatch.delenv("RESEARCH_MAX_LLM_USD", raising=False)
    rt = Runtime(Store(tmp_path))

    async def nothing(job_id):
        return None

    monkeypatch.setattr(rt, "execute", nothing)
    return rt


async def test_an_organization_job_within_its_month_starts_at_once_whatever_the_day(runtime):
    job = runtime.create(RESEARCH, "k1", delegation=org("appvillis", monthly=1000))
    assert job["status"] == "working"
    assert job["decision"] | {"at": None} == {"by": "allowance", "principal": "org:appvillis", "worstCaseUsd": 6.5,
                                              "keyClass": "organization", "spentMonthUsd": 0.0,
                                              "monthlyCeilingUsd": 1000.0, "approved": True, "at": None}
    assert "monthLedger" not in job["decision"]  # the key's own ceiling governs it, not the agents' month stop


async def test_an_organization_job_that_would_cross_its_month_waits_for_the_operator(runtime):
    first = runtime.create(RESEARCH, "k1", delegation=org("appvillis", monthly=10))
    assert first["status"] == "working"
    second = runtime.create(RESEARCH | {"inputs": {"market": "VPN"}}, "k2", delegation=org("appvillis", monthly=10))
    assert second["status"] == "input_required" and second.get("decision") is None
    # another organization's month is its own
    other = runtime.create(RESEARCH | {"inputs": {"market": "VPN"}}, "k3", delegation=org("passioncode", monthly=10))
    assert other["status"] == "working"


def test_the_month_counts_only_this_months_jobs(runtime):
    store = runtime.store
    job, _ = store.create(RESEARCH, "old", delegation=org("appvillis"))
    store.decide(job["id"], job["proposal"]["digest"], True, by={"by": "allowance", "worstCaseUsd": 6.5})
    month = allowance.this_month()
    assert allowance.spent_this_month(store, "org:appvillis", month) == pytest.approx(6.5)
    assert allowance.spent_this_month(store, "org:appvillis", "1999-01") == 0.0


# --- the report memory -----------------------------------------------------------------------------------------


def finished(store, request, delegation, report="# Report\n"):
    job, _ = store.create(request, "done-" + str(len(store.jobs())), delegation=delegation)
    store.decide(job["id"], job["proposal"]["digest"], True, by={"by": "allowance", "worstCaseUsd": 6.5})
    store.transition(job["id"], "completed", "completed")
    if report is not None:
        run = store.root / "runs" / job["id"]
        run.mkdir(parents=True, exist_ok=True)
        (run / "report.md").write_text(report)
    return store.job(job["id"])


async def test_a_ready_report_of_the_same_research_answers_instead_of_a_new_run(runtime):
    done = finished(runtime.store, RESEARCH, org("appvillis", "org-appvillis"))
    again = runtime.create(RESEARCH | {"inputs": {"market": "  esim "}}, "k-new", delegation=org("appvillis", "org-appvillis"))
    assert again["id"] == done["id"] and again["reused"] is True
    assert len(runtime.store.jobs()) == 1  # nothing new was created, nothing spent
    assert any(e["kind"] == "job.reused" for e in runtime.store.events(after=0, limit=50)["events"])


async def test_fresh_true_starts_a_new_run_even_with_a_ready_report(runtime):
    done = finished(runtime.store, RESEARCH, org("appvillis"))
    job = runtime.create(RESEARCH | {"fresh": True}, "k-fresh", delegation=org("appvillis"))
    assert job["id"] != done["id"] and not job.get("reused")


async def test_no_reuse_across_organizations_other_inputs_or_without_a_report(runtime):
    finished(runtime.store, RESEARCH, org("passioncode"))
    finished(runtime.store, RESEARCH | {"inputs": {"market": "VPN"}}, org("appvillis"))
    finished(runtime.store, RESEARCH | {"inputs": {"market": "Travel"}}, org("appvillis"), report=None)
    for inputs in ({"market": "eSIM"}, {"market": "Travel"}):
        job = runtime.create(RESEARCH | {"inputs": inputs}, "k-" + inputs["market"], delegation=org("appvillis"))
        assert not job.get("reused")


async def test_a_personal_key_never_reuses(runtime):
    personal = {"principal": "client:personal-key", "caller": "client:personal-key", "tier": "client",
                "keyClass": "interactive"}
    finished(runtime.store, RESEARCH, personal)
    job = runtime.create(RESEARCH, "k-personal", delegation=personal)
    assert not job.get("reused")


def test_the_listing_is_the_organizations_own_newest_first(runtime):
    store = runtime.store
    a = finished(store, RESEARCH, org("appvillis", "org-appvillis"))
    b = finished(store, RESEARCH | {"inputs": {"market": "VPN"}}, org("appvillis", "org-appvillis-2"))
    finished(store, RESEARCH | {"inputs": {"market": "Secret"}}, org("passioncode"))
    listed = reports.listing(store, org("appvillis"))
    assert listed["organization"] == "appvillis"
    assert [r["id"] for r in listed["reports"]] == [b["id"], a["id"]]
    assert listed["reports"][0]["by"] == "org-appvillis-2"
    assert [r["id"] for r in reports.listing(store, org("appvillis"), query="vpn")["reports"]] == [b["id"]]
    assert reports.listing(store, None)["reports"] == []


# --- through the cloud's /mcp ----------------------------------------------------------------------------------


def call(name, arguments, rid=1):
    return {"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


def bearer(key):
    return {"Authorization": "Bearer " + key}


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    monkeypatch.setenv("PROWL_API_KEY", "p")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    clients = FileClients(tmp_path / "keys" / "clients.json")
    app = create_app(tmp_path / "data", "service-value", None, cloud=CloudSettings(origin=ORIGIN, clients=clients))

    async def nothing(job_id):
        return None

    monkeypatch.setattr(app.state.runtime, "execute", nothing)
    return app, clients


async def test_two_people_of_one_organization_share_its_reports_through_mcp(cloud):
    app, clients = cloud
    key = clients.add("org-appvillis", ["read", "research.run"], key_class="organization", org="appvillis")
    other = clients.add("org-passioncode", ["read", "research.run"], key_class="organization", org="passioncode")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
                                 headers={"x-forwarded-proto": "https"}) as c:
        args = {"idempotencyKey": "person-a", "runbook": "market-pulse", "inputs": {"market": "eSIM"}}
        r = await c.post("/mcp", json=call("research.run", args), headers=bearer(key))
        job_id = r.json()["result"]["structuredContent"]["job"]["id"]
        job = app.state.store.job(job_id)
        assert job["delegation"]["principal"] == "org:appvillis" and job["delegation"]["caller"] == "client:org-appvillis"
        app.state.store.transition(job_id, "completed", "completed")
        run = app.state.store.root / "runs" / job_id
        run.mkdir(parents=True, exist_ok=True)
        (run / "report.md").write_text("# eSIM\n")
        # a second person with the same key and another idempotency key gets the ready report
        r = await c.post("/mcp", json=call("research.run", args | {"idempotencyKey": "person-b"}), headers=bearer(key))
        answer = r.json()["result"]["structuredContent"]
        assert answer["job"] == {"id": job_id, "status": "completed"} and answer["reused"]["id"] == job_id
        r = await c.post("/mcp", json=call("research.reports.list", {}), headers=bearer(key))
        assert [x["id"] for x in r.json()["result"]["structuredContent"]["reports"]] == [job_id]
        r = await c.post("/mcp", json=call("research.artifact.get", {"id": job_id, "name": "report.md"}), headers=bearer(key))
        assert not r.json()["result"].get("isError")
        # another organization neither lists nor reads it
        r = await c.post("/mcp", json=call("research.reports.list", {}), headers=bearer(other))
        assert r.json()["result"]["structuredContent"]["reports"] == []
        r = await c.post("/mcp", json=call("research.artifact.get", {"id": job_id, "name": "report.md"}), headers=bearer(other))
        assert r.json()["result"]["isError"]
        # the listing is also behind the execute door
        r = await c.post("/mcp", json=call("research.execute", {"operation": "research.reports.list", "arguments": {}}),
                         headers=bearer(key))
        assert not r.json()["result"].get("isError")
