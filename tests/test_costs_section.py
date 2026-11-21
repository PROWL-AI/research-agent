"""B-155, rule R33 O16 (agents database D-74, `patterns/costs-panel` 1.0.0, contract DEC-0183): the Costs section.
Spend by UTC day, ISO week and month; limits unset until a person sets them and checked before every paid call; one
edit, `spend.limits.set`, the dashboard's control and a capability alike, every change recorded; the emergency stop
of USD 500 a day and USD 1000 a month on by default and moved only with the operator's decision."""
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from research_agent.llm import LLMClient, LLMError
from research_agent.prowl_client import ProwlClient, ToolCallError
from research_agent.service import costs
from research_agent.service.app import CloudSettings, create_app
from research_agent.service.clients import FileClients
from research_agent.service.runtime import ObservedLLM, ObservedProwl
from research_agent.service.vendor import costs_panel as cp

VENDORED = Path(__file__).resolve().parent.parent / "research_agent" / "service" / "vendor" / "costs_panel.py"
# sha256 of patterns/costs-panel/code/costs_panel.py at agents-database commit a2019216
PATTERN_SHA256 = "c96b2643d0b623b248c6e56b797838f7fc89aca0e508572b25848b72f75a14b6"
AGENT = {"Authorization": "Bearer agent-value"}
POST = {"X-Prowl-Request": "1"}
ORIGIN = "https://research.example.test"
OPERATOR = {"by": "operator", "via": "chat", "action": "spend.limits.set", "target": "costs.day",
            "instruction": "raise the day limit to 50", "at": "2026-11-21T12:00:00Z"}


@pytest.fixture(autouse=True)
def provider_key(monkeypatch):
    # a paid job is created only with a provider key connected; no test here sends anything
    monkeypatch.setenv("PROWL_API_KEY", "offline-test-value")


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path, "host-value", "agent-value")


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:18764") as c:
        yield c
    await app.state.runtime.close()


def paid_job(app, key="job-1"):
    return app.state.runtime.create({"kind": "tool", "tool": "google_news", "params": {"q": "ai agents"}}, key, via="dashboard")


def spend(store, job, usd, kind="tool", name="google_news"):
    call = store.start_call(job["id"], kind, name, {})
    return store.finish_call(call, status="completed", costUsd=usd, costBasis="provider" if usd is not None else "unknown")


def execute(operation, arguments=None, key=None, meta=None):
    args = {"operation": operation, "arguments": arguments or {}} | ({"idempotencyKey": key} if key else {})
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "research.execute", "arguments": args} | ({"_meta": meta} if meta else {})}


async def result_of(client, body, headers=AGENT):
    response = await client.post("/mcp", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["result"]


async def login(client):
    url = (await client.post("/fabric/v1/login-code", headers={"Authorization": "Bearer host-value"})).json()["url"]
    assert (await client.get(url)).status_code == 302


def test_the_vendored_module_is_the_patterns_code_byte_for_byte():
    assert hashlib.sha256(VENDORED.read_bytes()).hexdigest() == PATTERN_SHA256
    assert cp.__version__ == "1.0.0"


def test_only_the_emergency_stop_is_set_by_default(app):
    limits = costs.panel(app.state.store)["limits"]
    assert {k: v["limitUsd"] for k, v in limits.items()} == {
        "costs.order": None, "costs.day": None, "costs.week": None, "costs.month": None,
        "emergency.day": 500.0, "emergency.month": 1000.0}
    assert limits["emergency.day"]["enforced"] and limits["emergency.month"]["enforced"]
    assert costs.refusal(app.state.store, paid_job(app), 1.0) is None


def test_a_priced_call_counts_its_price_and_an_unpriced_one_its_worst_case_never_zero(app):
    store, job = app.state.store, paid_job(app)
    spend(store, job, 0.25)
    spend(store, job, None)                                    # the provider gave no price: the worst case, 1 USD
    spend(store, job, None, kind="llm", name="unlisted/model")  # an unlisted model: the top of the price table
    store.start_call(job["id"], "tool", "google_news", {})      # in flight: unpriced, so parallel calls see it
    tutorial = app.state.runtime.create({"kind": "tutorial"}, "learn", via="dashboard")
    spend(store, tutorial, 99.0)                                # a learning job is never money
    panel = costs.panel(store)
    assert panel["unpriced"] == 3
    assert panel["windows"]["day"]["spent_usd"] == pytest.approx(0.25 + 1.0 + costs.llm_call_worst_usd("unlisted/model") + 1.0)
    assert costs.llm_call_worst_usd("unlisted/model") > 1.0
    assert panel["series"]["day"][-1]["state"] == "lower_bound" and panel["series"]["day"][-1]["usd"] == 0.25
    assert len(panel["series"]["day"]) == 31 and len(panel["series"]["week"]) == 12 and len(panel["series"]["month"]) == 12


def test_the_emergency_stop_refuses_first_and_says_so_once_per_job(app):
    store, job = app.state.store, paid_job(app)
    spend(store, job, 499.5)
    assert costs.refusal(store, job, 0.5) is None  # at the line it passes
    said = costs.refusal(store, job, 1.0)
    assert said.startswith("Spend limit reached (emergency_day: 499.50 of 500.00 USD")
    costs.refusal(store, job, 1.0)
    events = [e for e in store.events(0, 200)["events"] if e.get("kind") == "costs.limit_reached"]
    assert len(events) == 1 and "аварийный стоп за сутки" in json.dumps(events[0], ensure_ascii=False)


def test_a_day_limit_and_the_orders_limit_are_checked_before_the_call(app):
    store, job, other = app.state.store, paid_job(app), paid_job(app, "job-2")
    costs.set_limit(store, {"limitId": "costs.day", "limitUsd": 5, "reason": "a test day", "idempotencyKey": "k-day"}, via="agent")
    spend(store, job, 4.5)
    assert costs.refusal(store, job, 0.5) is None
    assert "day: 4.50 of 5.00" in costs.refusal(store, job, 1.0)
    assert "day:" in costs.refusal(store, other, 1.0)  # the day is the service's, whoever spends
    costs.set_limit(store, {"limitId": "costs.day", "limitUsd": None, "reason": "cleared", "idempotencyKey": "k-clear"},
                    via="dashboard", decision={"by": "operator", "instruction": "clear it", "at": "2026-11-21T12:00:00Z"})
    costs.set_limit(store, {"limitId": "costs.order", "limitUsd": 5, "reason": "one order", "idempotencyKey": "k-order"}, via="agent")
    assert "order: 4.50 of 5.00" in costs.refusal(store, job, 1.0)
    assert costs.refusal(store, other, 1.0) is None    # another order has its own line


async def test_the_paid_clients_ask_before_they_journal_and_send_nothing_when_refused(app, monkeypatch):
    store, job = app.state.store, paid_job(app)
    costs.set_limit(store, {"limitId": "costs.day", "limitUsd": 0.5, "reason": "tight", "idempotencyKey": "k1"}, via="agent")
    spend(store, job, 0.4)  # one more tool call (worst case 1 USD) or model call (about 0.16 USD) would pass the line

    async def never(*args, **kwargs):
        raise AssertionError("a refused call must not be sent")

    monkeypatch.setattr(ProwlClient, "_invoke", never)
    prowl = ObservedProwl(api_key="k", mcp_url="https://prowl.example.test/mcp").observe(store, job)
    with pytest.raises(ToolCallError) as refused:
        await prowl._invoke("prowl_call_tool", {"tool_name": "google_news", "params": {}})
    assert refused.value.stops_run and refused.value.cost_usd == 0.0 and "nothing was sent" in str(refused.value)
    llm = ObservedLLM(base_url="https://llm.example.test", api_key="k", model_cheap="z-ai/glm-5.3",
                      model_strong="moonshotai/kimi-k3.1-pro").observe(store, job)
    with pytest.raises(LLMError) as stopped:
        llm._before_send()
    assert "Spend limit reached (day" in str(stopped.value) and stopped.value.retryable is False
    assert len(store.calls(job["id"])) == 1  # only the call that was paid before: a refusal journals nothing
    assert isinstance(llm, LLMClient)


def test_tightening_is_the_callers_act_and_loosening_needs_the_operators_decision(app):
    store = app.state.store
    first = costs.set_limit(store, {"limitId": "costs.month", "limitUsd": 100, "reason": "first", "idempotencyKey": "a"}, via="agent", by_ref="agent")
    assert first["change"]["after"] == {"limitUsd": 100.0, "enforced": True} and first["change"]["by"] == "agent"
    again = costs.set_limit(store, {"limitId": "costs.month", "limitUsd": 100, "reason": "first", "idempotencyKey": "a"}, via="agent")
    assert again["repeated"] and again["change"]["id"] == first["change"]["id"]
    for change in ({"limitUsd": 200}, {"limitUsd": None}, {"enforced": False}):
        with pytest.raises(cp.Refused) as refused:
            costs.set_limit(store, {"limitId": "costs.month", "reason": "more", "idempotencyKey": "b", **change}, via="agent")
        assert refused.value.code == "operator-decision-required"
    with pytest.raises(cp.Refused) as lifted:
        costs.set_limit(store, {"limitId": "emergency.day", "enforced": False, "reason": "agent", "idempotencyKey": "c"}, via="agent")
    assert lifted.value.code == "operator-decision-required"
    raised = costs.set_limit(store, {"limitId": "costs.month", "limitUsd": 200, "reason": "more", "idempotencyKey": "d"},
                             via="agent", decision=OPERATOR)
    assert raised["change"]["by"] == "operator" and raised["change"]["before"]["limitUsd"] == 100.0
    assert [c["id"] for c in costs.panel(store)["history"]] == [raised["change"]["id"], first["change"]["id"]]
    assert "raise the day limit" not in json.dumps(costs.panel(store))  # the decision's words stay in the book
    lines = (store.root / costs.LIMITS_FILE).read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[1])["decision"] == OPERATOR


async def test_the_two_operations_sit_behind_the_doors_with_the_contracts_refusals(client):
    panel = await result_of(client, execute("costs.panel"))
    assert panel["isError"] is False and panel["structuredContent"]["schema"] == "costs-panel/1"
    assert panel["structuredContent"]["edit"]["action"] == "spend.limits.set"
    args = {"limitId": "costs.week", "limitUsd": 40, "reason": "a week of research"}
    no_key = await result_of(client, execute("spend.limits.set", args))
    assert no_key["structuredContent"]["error"]["code"] == "idempotency-required"
    done = await result_of(client, execute("spend.limits.set", args, key="week-1"))
    assert done["isError"] is False and done["structuredContent"]["change"]["after"]["limitUsd"] == 40.0
    assert (await result_of(client, execute("spend.limits.set", args, key="week-1")))["structuredContent"]["repeated"] is True
    more = {"limitId": "costs.week", "limitUsd": 80, "reason": "a bigger week"}
    refused = await result_of(client, execute("spend.limits.set", more, key="week-2"))
    assert refused["isError"] and refused["structuredContent"]["error"]["code"] == "operator-decision-required"
    relayed = await result_of(client, execute("spend.limits.set", more, key="week-2", meta={"decision": OPERATOR}))
    assert relayed["isError"] is False and relayed["structuredContent"]["change"]["by"] == "operator"
    unknown = await result_of(client, execute("spend.limits.set", {"limitId": "costs.year", "limitUsd": 1, "reason": "x"}, key="y"))
    assert unknown["isError"]
    found = (await result_of(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": "research.search", "arguments": {"query": "limit"}}}))
    by_name = {o["name"]: o for o in found["structuredContent"]["operations"]}
    assert by_name["spend.limits.set"]["gate"] == "relayed"
    assert found["_meta"]["hints"]["operations"]["spend.limits.set"] == {"effect": "write", "idempotency": "required"}
    listed = (await result_of(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}))["tools"]
    assert len(listed) == 4 and "spend.limits.set" not in {t["name"] for t in listed}


async def test_the_dashboard_shows_the_section_and_edits_a_limit_as_the_operator(client, app):
    assert (await client.get("/api/costs")).status_code == 401
    await login(client)
    state = (await client.get("/api/state")).json()
    assert state["costs"]["schema"] == "costs-panel/1" and state["costs"]["emergency"]["day"]["limit_usd"] == 500.0
    assert (await client.post("/api/costs/limits", json={})).status_code == 403  # the request header is required
    body = {"limitId": "costs.day", "limitUsd": 20, "enforced": True, "reason": "день исследований", "idempotencyKey": "ui-1"}
    saved = (await client.post("/api/costs/limits", json=body, headers=POST)).json()
    assert saved["change"]["by"] == "operator" and saved["change"]["via"] == "dashboard"
    raised = await client.post("/api/costs/limits", json={**body, "limitUsd": 60, "idempotencyKey": "ui-2"}, headers=POST)
    assert raised.status_code == 200 and raised.json()["change"]["after"]["limitUsd"] == 60.0  # the operator's own act
    bad = await client.post("/api/costs/limits", json={**body, "limitUsd": -1, "idempotencyKey": "ui-3"}, headers=POST)
    assert bad.status_code == 400 and bad.json()["code"] == "invalid-amount"
    panel = (await client.get("/api/costs")).json()
    assert panel["windows"]["day"]["limit_usd"] == 60.0 and len(panel["history"]) == 2
    kinds = [e["kind"] for e in app.state.store.events(0, 200)["events"]]
    assert kinds.count("costs.limit_changed") == 2
    script = (Path(costs.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    for needle in ("/api/costs/limits", "limitsPanel()", "Расходы по неделям", "Расходы по месяцам", "История изменений лимитов"):
        assert needle in script


async def test_the_well_known_names_the_edit_and_the_usage_report_keeps_its_pinned_shape(client, app):
    health = (await client.get("/.well-known/fabric-service")).json()
    assert {"costs.panel", "spend.limits.set"} <= set(health["surfaces"]["mcp"]["capabilities"])
    usage = (await client.get("/fabric/v1/usage", headers={"Authorization": "Bearer host-value"})).json()
    assert set(usage) == {"protocol", "service", "generatedAt", "currency", "days"}


async def test_a_cloud_client_key_reaches_neither_operation(tmp_path):
    clients = FileClients(tmp_path / "keys" / "clients.json")
    app = create_app(tmp_path / "data", "service-value", None, cloud=CloudSettings(origin=ORIGIN, clients=clients))
    key = {"Authorization": "Bearer " + clients.add("anna", ["read", "research.run", "tools.call"])}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN, headers={"x-forwarded-proto": "https"}) as c:
        for body in (execute("costs.panel"),
                     execute("spend.limits.set", {"limitId": "costs.day", "limitUsd": 1, "reason": "x"}, key="k")):
            result = await result_of(c, body, headers=key)
            assert result["isError"] and result["structuredContent"]["error"]["code"] == "scope-not-granted"
    await app.state.runtime.close()
    assert not (tmp_path / "data" / costs.LIMITS_FILE).exists()
