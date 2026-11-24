"""B-162: an organization key reads its own organization's spend (`costs.panel`, scope `costs.read`).

The operator's word of 2026-11-24 09:05 UTC (Telegram, relayed by the Fabric CEO, request 1f46162c): the team asked
whether it sees the costs panel; an organization key now reads its own organization's spend and nothing of anyone
else's, and never edits a limit.
"""
from __future__ import annotations

import httpx
import pytest

from research_agent.service import costs
from research_agent.service.app import CloudSettings, create_app
from research_agent.service.cli import client_command
from research_agent.service.clients import COSTS_READ_SCOPE, FileClients

ORIGIN = "https://research.example.test"
RESEARCH = {"kind": "research", "runbook": "market-pulse", "inputs": {"market": "eSIM"}}


def call(name, arguments, rid=1):
    return {"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


def bearer(key):
    return {"Authorization": "Bearer " + key}


def org(name, monthly=1000.0):
    return {"principal": "org:" + name, "caller": "client:org-" + name, "chain": [], "kid": None, "tier": "client",
            "keyClass": "organization", "org": name, "monthlyUsd": monthly}


def paid(store, delegation, usd, key):
    job, _ = store.create(RESEARCH, key, delegation=delegation)
    store.decide(job["id"], job["proposal"]["digest"], True, by={"by": "allowance", "worstCaseUsd": usd})
    c = store.start_call(job["id"], "tool", "google_news", {})
    store.finish_call(c, status="completed", costUsd=usd, costBasis="provider")
    store.transition(job["id"], "completed", "completed")
    return job


# --- the scope -------------------------------------------------------------------------------------------------


def test_an_organization_key_is_issued_with_costs_read(tmp_path):
    clients = FileClients(tmp_path / "clients.json")
    key = clients.add("org-appvillis", ["read", "research.run"], key_class="organization", org="appvillis")
    assert COSTS_READ_SCOPE in clients.verify(key)["scopes"]


@pytest.mark.parametrize("key_class", ["automated", "interactive"])
def test_costs_read_belongs_to_an_organization_key_only(tmp_path, key_class):
    with pytest.raises(ValueError, match="organization key"):
        FileClients(tmp_path / "clients.json").add("k", ["read", COSTS_READ_SCOPE], key_class=key_class)


def test_grant_adds_costs_read_to_a_key_already_delivered_without_rotating_it(tmp_path):
    clients = FileClients(tmp_path / "clients.json")
    key = clients.add("org-appvillis", ["read"], key_class="organization", org="appvillis")
    data = clients._load()
    data["org-appvillis"]["scopes"] = ["read"]  # a key issued before B-162
    clients._write(data)
    assert clients.grant("org-appvillis", [COSTS_READ_SCOPE]) == ["read", COSTS_READ_SCOPE]
    assert COSTS_READ_SCOPE in clients.verify(key)["scopes"]  # the same key still answers


def test_grant_refuses_costs_read_on_another_class_a_desk_and_an_unknown_key(tmp_path):
    clients = FileClients(tmp_path / "clients.json")
    clients.add("pipeline", ["read"])
    clients.add_desk("desk", ["read"], 10)
    with pytest.raises(ValueError, match="organization key"):
        clients.grant("pipeline", [COSTS_READ_SCOPE])
    with pytest.raises(ValueError, match="desk key"):
        clients.grant("desk", ["read"])
    with pytest.raises(KeyError):
        clients.grant("nobody", ["read"])


def test_the_cli_grants_a_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("PROWL_RESEARCH_ROOT", str(tmp_path))
    lines = []
    assert client_command(["add", "org-x", "--class", "organization", "--org", "x"], out=lines.append) == 0
    assert client_command(["grant", "org-x", "--scopes", "tools.call"], out=lines.append) == 0
    assert lines[-1] == "org-x: scopes read,costs.read,tools.call"


# --- the read --------------------------------------------------------------------------------------------------


def test_the_organizations_panel_counts_its_own_jobs_only(tmp_path):
    from research_agent.service.store import Store

    store = Store(tmp_path)
    paid(store, org("appvillis"), 2.5, "a")
    paid(store, org("passioncode"), 7.0, "b")
    paid(store, None, 11.0, "c")  # the operator's own
    data = costs.org_panel(store, org("appvillis"))
    assert data["windows"]["month"]["spent_usd"] == pytest.approx(2.5)
    assert data["organization"]["spentMonthUsd"] == pytest.approx(2.5)
    assert data["organization"]["leftMonthUsd"] == pytest.approx(997.5)
    assert data["scope"] == {"kind": "organization", "organization": "appvillis"}
    assert "edit" not in data and "history" not in data and "limits" not in data
    assert all(w["limit_usd"] is None and not w["tripped"] for w in data["windows"].values())
    with pytest.raises(ValueError):
        costs.org_panel(store, {"principal": "client:pipeline"})


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    monkeypatch.setenv("PROWL_API_KEY", "p")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    clients = FileClients(tmp_path / "keys" / "clients.json")
    app = create_app(tmp_path / "data", "service-value", None, cloud=CloudSettings(origin=ORIGIN, clients=clients))
    return app, clients


async def test_an_organization_key_reads_its_own_spend_and_never_edits_a_limit(cloud):
    app, clients = cloud
    key = clients.add("org-appvillis", ["read", "research.run"], key_class="organization", org="appvillis")
    plain = clients.add("pipeline", ["read", "research.run"])
    paid(app.state.store, org("appvillis"), 3.0, "a")
    paid(app.state.store, org("passioncode"), 9.0, "b")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
                                 headers={"x-forwarded-proto": "https"}) as c:
        for request in (call("costs.panel", {}), call("research.execute", {"operation": "costs.panel", "arguments": {}})):
            r = await c.post("/mcp", json=request, headers=bearer(key))
            result = r.json()["result"]
            assert not result.get("isError"), result
            data = result["structuredContent"]
            assert data["scope"]["organization"] == "appvillis"
            assert data["windows"]["month"]["spent_usd"] == pytest.approx(3.0)
        # the edit stays the operator's
        r = await c.post("/mcp", json=call("research.execute", {"operation": "spend.limits.set", "idempotencyKey": "k1",
                                                                 "arguments": {"limitId": "costs.day", "limitUsd": 1}}),
                         headers=bearer(key))
        assert r.json()["result"]["isError"]
        # a key of no organization still reads nothing
        r = await c.post("/mcp", json=call("costs.panel", {}), headers=bearer(plain))
        assert r.json()["result"]["isError"]
