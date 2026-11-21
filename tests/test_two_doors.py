"""B-154, rule R33 O15 (agents database D-72, `patterns/compact-mcp` 1.2.0): the service's MCP listing is two doors,
`research.search` and `research.execute`, beside the protocol's two job tools. Every operation stays reachable with its
own gate, schema and idempotency; an operation's own tool name left the listing and still answers (R28)."""
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from research_agent.agent import compact_mcp
from research_agent.service.app import CloudSettings, create_app
from research_agent.service.clients import FileClients
from research_agent.service.protocol import (CAPABILITIES, DESK_SCHEMAS, EXECUTE_TOOL, JOB_TOOLS, PURPOSES,
                                             RETIRED_SINCE, SEARCH_TOOL, compact_surface, compact_tools,
                                             operation_names, tools_list)
from research_agent.runbook import get_runbook

VENDORED = Path(__file__).resolve().parent.parent / "research_agent" / "agent" / "compact_mcp.py"
HEADER = "# vendored from patterns/compact-mcp/code/compact_mcp.py@1.2.0\n"
# sha256 of patterns/compact-mcp/code/compact_mcp.py at agents-database commit 3de5708b
PATTERN_SHA256 = "f2f25331562ac64e222b960064f893d1a06e7b1f90b575ce058b2aa4db7dacac"
ORIGIN = "https://research.example.test"
AGENT = {"Authorization": "Bearer agent-value"}


def rpc(method, params=None, rid=1):
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}


def call(name, arguments=None):
    return rpc("tools/call", {"name": name, "arguments": arguments or {}})


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path, "host-value", "agent-value")


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:18764") as c:
        yield c
    await app.state.runtime.close()


@pytest.fixture
def clients(tmp_path):
    return FileClients(tmp_path / "keys" / "clients.json")


@pytest.fixture
async def cloud(tmp_path, clients):
    app = create_app(tmp_path / "data", "service-value", None, cloud=CloudSettings(origin=ORIGIN, clients=clients))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
                                 headers={"x-forwarded-proto": "https"}) as c:
        yield c
    await app.state.runtime.close()


async def result_of(client, body, headers=AGENT, path="/mcp"):
    response = await client.post(path, json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["result"]


def test_the_vendored_module_is_the_patterns_code_byte_for_byte():
    text = VENDORED.read_text(encoding="utf-8")
    assert text.startswith(HEADER)
    assert hashlib.sha256(text[len(HEADER):].encode("utf-8")).hexdigest() == PATTERN_SHA256
    assert compact_mcp.__version__ == "1.2.0"


async def test_the_listing_is_two_doors_and_the_job_tools_and_passes_the_bases_check(client):
    tools = (await result_of(client, rpc("tools/list")))["tools"]
    assert [t["name"] for t in tools] == [SEARCH_TOOL, EXECUTE_TOOL, *JOB_TOOLS]
    verdict = compact_mcp.check({"tools": tools})
    assert verdict["within"] and verdict["findings"] == [] and verdict["jobs"] == list(JOB_TOOLS)
    # the desk's four tools fold behind the same doors in the cloud
    assert compact_mcp.check({"tools": compact_tools(desk=True)})["within"]
    assert len(compact_tools(desk=True)) == 4


async def test_the_full_listing_stays_on_its_own_surface(client):
    tools = (await result_of(client, rpc("tools/list"), path="/mcp?surface=capabilities"))["tools"]
    assert [t["name"] for t in tools] == [t["name"] for t in tools_list()]
    assert set(CAPABILITIES) <= {t["name"] for t in tools}


def test_every_operation_has_a_written_purpose_and_a_real_example():
    assert set(PURPOSES) == set(CAPABILITIES) | set(DESK_SCHEMAS)
    for name, text in PURPOSES.items():
        assert len(text) <= compact_mcp.PURPOSE_MAX and text.endswith(".") and "\n" not in text, name
    surface = compact_surface(desk=True)
    assert surface.reachable() == sorted(operation_names(desk=True))  # parity (R33 O8): nothing is lost
    example = surface.operations["research.run"]["example"]
    assert {spec.name for spec in get_runbook(example["runbook"]).meta.inputs} >= set(example["inputs"])
    for name, op in surface.operations.items():
        assert compact_mcp.validate(op["example"], {k: v for k, v in op["inputSchema"].items() if k != "$id"}) == [], name


async def test_search_answers_the_closed_catalogue_with_hints_beside_it(client):
    result = await result_of(client, call(SEARCH_TOOL))
    answer = result["structuredContent"]
    assert result["isError"] is False and answer["schema"] == "compact-mcp-search/1"
    assert [o["name"] for o in answer["operations"]] == list(CAPABILITIES) and answer["total"] == answer["matched"] == 5
    assert "nextCursor" not in answer and set(answer) <= {"schema", "query", "total", "matched", "operations"}
    hints = result["_meta"]["hints"]["operations"]
    assert hints["research.run"] == {"effect": "money", "idempotency": "required"}
    assert hints["research.list_runbooks"] == {"effect": "read", "idempotency": "none"}
    found = (await result_of(client, call(SEARCH_TOOL, {"query": "runbook budgets"})))["structuredContent"]
    assert [o["name"] for o in found["operations"]] == ["research.list_runbooks"]
    bad = await result_of(client, call(SEARCH_TOOL, {"limit": 0}))
    assert bad["isError"] and bad["structuredContent"]["error"]["code"] == "invalid-arguments"


async def test_execute_takes_the_operations_own_path(client, app):
    listed = await result_of(client, call(EXECUTE_TOOL, {"operation": "research.list_runbooks"}))
    assert listed["isError"] is False and listed["structuredContent"]["output"]["runbooks"]
    assert "retired" not in listed.get("_meta", {})
    # a job capability takes the key its own tool takes: execute's, or the one inside its arguments
    refused = await result_of(client, call(EXECUTE_TOOL, {"operation": "research.tutorial"}))
    assert refused["isError"] and refused["structuredContent"]["error"]["code"] == "idempotency-required"
    first = await result_of(client, call(EXECUTE_TOOL, {"operation": "research.tutorial", "idempotencyKey": "doors-1"}))
    again = await result_of(client, call(EXECUTE_TOOL, {"operation": "research.tutorial", "arguments": {"idempotencyKey": "doors-1"}}))
    by_name = await result_of(client, call("research.tutorial", {"idempotencyKey": "doors-1"}))
    job = first["structuredContent"]["job"]["id"]
    assert again["structuredContent"]["job"]["id"] == job == by_name["structuredContent"]["job"]["id"]
    assert len(app.state.store.jobs()) == 1
    two = await result_of(client, call(EXECUTE_TOOL, {"operation": "research.tutorial", "idempotencyKey": "a",
                                                      "arguments": {"idempotencyKey": "b"}}))
    assert two["structuredContent"]["error"]["code"] == "invalid-arguments"
    # the operation's own schema refuses through execute as by its own name
    wrong = await result_of(client, call(EXECUTE_TOOL, {"operation": "research.artifact.get", "arguments": {"id": "x"}}))
    assert wrong["isError"]


async def test_typed_refusals_of_execute(client):
    unknown = await result_of(client, call(EXECUTE_TOOL, {"operation": "research.list_runbook"}))
    error = unknown["structuredContent"]["error"]
    assert error["code"] == "unknown-operation" and error["data"]["near"][0] == "research.list_runbooks"
    bad = await result_of(client, call(EXECUTE_TOOL, {"arguments": {}}))
    assert bad["structuredContent"]["error"]["code"] == "invalid-arguments"
    assert (await client.post("/mcp", json=call("research.nothing"), headers=AGENT)).status_code == 400


async def test_an_old_tool_name_is_off_the_listing_and_still_answers_marked_retired(client):
    result = await result_of(client, call("research.list_runbooks"))
    assert result["isError"] is False and result["structuredContent"]["output"]["runbooks"]
    assert result["_meta"]["retired"] == {"since": RETIRED_SINCE, "replacedBy": EXECUTE_TOOL}
    # a listed job tool is not retired, and the full surface serves each capability under its own name
    job = (await result_of(client, call("research.tutorial", {"idempotencyKey": "old-name"})))["structuredContent"]["job"]["id"]
    assert "retired" not in (await result_of(client, call("fabric.job.get", {"id": job}))).get("_meta", {})
    full = await result_of(client, call("research.list_runbooks"), path="/mcp?surface=capabilities")
    assert "retired" not in full.get("_meta", {})


async def test_every_call_is_audited_with_its_route_and_answered_calls_are_counted(client, app, caplog, tmp_path):
    caplog.set_level("INFO", logger="research_agent.service.protocol")
    await result_of(client, call(SEARCH_TOOL))
    await result_of(client, call(EXECUTE_TOOL, {"operation": "research.list_runbooks"}))
    await result_of(client, call("research.list_runbooks"))
    await result_of(client, call(EXECUTE_TOOL, {"operation": "research.nope"}))
    lines = [r.getMessage() for r in caplog.records if "event=mcp.call" in r.getMessage()]
    assert [(" via=search " in line, " via=execute " in line, " via=name " in line) for line in lines] == [
        (True, False, False), (False, True, False), (False, False, True), (False, True, False)]
    assert lines[-1].endswith("outcome=unknown-operation") and lines[0].endswith("outcome=ok")
    days = json.loads((tmp_path / "mcp-usage.json").read_text())["days"]
    assert sum(day.get("research.list_runbooks", 0) for day in days.values()) == 2
    calls = (await result_of(client, call(SEARCH_TOOL, {"names": ["research.list_runbooks"]})))["structuredContent"]
    assert calls["operations"][0]["calls"] == 2


async def test_execute_never_opens_what_the_operations_own_scope_refuses(cloud, clients):
    reader = {"Authorization": "Bearer " + clients.add("reader", ["read"])}
    paid = call(EXECUTE_TOOL, {"operation": "research.tools.call", "idempotencyKey": "k",
                               "arguments": {"tool": "google_news", "params": {"q": "x"}}})
    refused = await result_of(cloud, paid, headers=reader)
    assert refused["isError"] and refused["structuredContent"]["error"]["code"] == "scope-not-granted"
    assert (await result_of(cloud, call(EXECUTE_TOOL, {"operation": "research.list_runbooks"}), headers=reader))["isError"] is False
    assert (await result_of(cloud, call(EXECUTE_TOOL, {"operation": "client.list"}), headers=reader))["isError"]


async def test_a_desk_key_finds_and_runs_its_operations_through_the_doors_and_reads_no_data(cloud, clients):
    desk = {"Authorization": "Bearer " + clients.add_desk("ania", ["read", "research.run"], 10)}
    tools = (await result_of(cloud, rpc("tools/list"), headers=desk))["tools"]
    assert [t["name"] for t in tools] == [SEARCH_TOOL, EXECUTE_TOOL, *JOB_TOOLS]
    found = (await result_of(cloud, call(SEARCH_TOOL, {"query": "desk"}), headers=desk))["structuredContent"]
    assert [o["name"] for o in found["operations"]] == list(DESK_SCHEMAS)
    issued = await result_of(cloud, call(EXECUTE_TOOL, {"operation": "client.issue", "arguments": {"name": "esim-vm"}}), headers=desk)
    assert issued["isError"] is False and issued["structuredContent"]["shownOnce"]
    data = await result_of(cloud, call(EXECUTE_TOOL, {"operation": "research.list_runbooks"}), headers=desk)
    assert data["isError"] and data["structuredContent"]["error"]["code"] == "scope-not-granted"
    assert (await cloud.post("/mcp", json=call(SEARCH_TOOL))).status_code == 401
