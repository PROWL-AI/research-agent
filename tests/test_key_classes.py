"""K1 (the operator's word of 2026-11-13, DEC-0074 of the Appvillis keys plan): a client key is `interactive` (a
person, or an agent a person calls in that moment) with no daily ceiling, or `automated` (a pipeline) that keeps its
ceiling. A key without a class reads as automated. A missing ceiling is null, never 0.

    «ключ Pro, который у нас есть, шарился на всех. Лимитов там никаких не делай ... Лимиты мы ограничиваем, только
    автоматические какие-то вещи ... Или генерации видео»
"""
from __future__ import annotations

import json

import pytest

from research_agent.service import allowance
from research_agent.service.clients import FileClients, PostgresClients
from research_agent.service.runtime import Runtime
from research_agent.service.store import Store

from test_cloud_clients import SqliteAsPostgres

RESEARCH = {"kind": "research", "runbook": "market-pulse", "inputs": {"market": "eSIM"}}


@pytest.fixture(params=["file", "postgres"])
def clients(request, tmp_path):
    if request.param == "file":
        return FileClients(tmp_path / "clients.json")
    connection = SqliteAsPostgres()
    return PostgresClients(lambda: connection)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("PROWL_API_KEY", "p")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    monkeypatch.delenv("RESEARCH_MAX_LLM_USD", raising=False)
    rt = Runtime(Store(tmp_path))

    async def nothing(job_id):
        pass

    monkeypatch.setattr(rt, "execute", nothing)
    return rt


def delegation(name, key):
    """What a job keeps of a verified client key, as `app.client_verdict` and `delegation.recorded` build it."""
    d = {"principal": "client:" + name, "caller": "client:" + name, "chain": [], "kid": None, "tier": "client",
         "keyClass": key["keyClass"]}
    return d | ({"dailyUsd": key["dailyUsd"]} if key["dailyUsd"] is not None else {})


def test_an_interactive_key_has_no_ceiling_and_reads_as_null(clients):
    key = clients.add("anna", ["read", "research.run"], key_class="interactive")
    assert clients.verify(key) == {"name": "anna", "scopes": ["read", "research.run"], "dailyUsd": None, "keyClass": "interactive"}
    (row,) = clients.list()
    assert row["dailyUsd"] is None and row["keyClass"] == "interactive"
    assert '"dailyUsd": null' in json.dumps(row)  # never 0
    with pytest.raises(ValueError, match="no daily ceiling"):
        clients.limit("anna", 50)
    with pytest.raises(ValueError, match="no daily ceiling"):
        clients.add("boris", ["read"], daily_usd=50, key_class="interactive")
    with pytest.raises(ValueError, match="key class"):
        clients.add("vera", ["read"], key_class="unlimited")


def test_a_key_without_a_class_reads_as_automated(clients):
    key = clients.add("old", ["read"])
    assert clients.verify(key) == {"name": "old", "scopes": ["read"], "dailyUsd": 10.0, "keyClass": "automated"}


def test_a_key_stored_before_classes_reads_as_automated(tmp_path):
    path = tmp_path / "clients.json"
    clients = FileClients(path)
    key = clients.add("old", ["read"], 20)
    data = json.loads(path.read_text())
    del data["old"]["keyClass"]
    path.write_text(json.dumps(data))
    assert clients.verify(key)["keyClass"] == "automated" and clients.verify(key)["dailyUsd"] == 20.0


def test_a_desk_issues_an_interactive_key_beyond_its_own_ceiling(clients):
    clients.add_desk("ania", ["read", "research.run"], 20)
    key = clients.desk_issue("ania", "person", ["read", "research.run"], key_class="interactive")
    assert clients.verify(key)["dailyUsd"] is None
    with pytest.raises(ValueError, match="at most 20"):
        clients.desk_issue("ania", "pipeline", ["read"], 25, key_class="automated")


async def test_an_interactive_key_spends_above_1000_a_day_without_waiting(runtime, tmp_path):
    clients = FileClients(tmp_path / "keys.json")
    person = clients.verify(clients.add("person", ["research.run"], key_class="interactive"))
    first = runtime.create(RESEARCH, "k1", delegation=delegation("person", person))
    # 200 runs of 6.5 USD worst case: 1300 USD in one UTC day, every one starts at once.
    jobs = [first] + [runtime.create(RESEARCH | {"inputs": {"market": f"m{i}"}}, f"k{i}", delegation=delegation("person", person))
                      for i in range(2, 201)]
    assert {j["status"] for j in jobs} == {"working"}
    assert allowance.spent_today(runtime.store, "client:person") == pytest.approx(1300.0)
    last = jobs[-1]["decision"]
    assert last["by"] == "allowance" and last["ceilingUsd"] is None and last["keyClass"] == "interactive"
    assert last["principal"] == "client:person"  # who spent, for the attribution (K2)
    assert runtime.store.events(after=0, limit=500)["events"][-1]["text"].startswith("Запуск по ключу без лимита")


async def test_an_automated_key_with_the_same_spend_waits(runtime, tmp_path):
    clients = FileClients(tmp_path / "keys.json")
    pipeline = clients.verify(clients.add("pipeline", ["research.run"], 1000, key_class="automated"))
    statuses = [runtime.create(RESEARCH | {"inputs": {"market": f"m{i}"}}, f"k{i}", delegation=delegation("pipeline", pipeline))["status"]
                for i in range(200)]
    assert statuses.count("working") == 153  # 153 × 6.5 = 994.5; the next would cross 1000
    assert set(statuses[153:]) == {"input_required"}


async def test_a_key_without_a_class_behaves_as_before(runtime):
    old = {"principal": "client:old", "caller": "client:old", "chain": [], "kid": None, "tier": "client"}
    assert runtime.create(RESEARCH, "k1", delegation=old)["status"] == "working"
    assert runtime.create(RESEARCH | {"inputs": {"market": "VPN"}}, "k2", delegation=old)["status"] == "input_required"
