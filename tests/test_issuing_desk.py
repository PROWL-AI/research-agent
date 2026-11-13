"""B-121 (research template 1.6.0, the issuing desk): a team's key steward holds a desk key. It calls only the desk
tools, issues keys within the grants and ceiling the operator's tool gave the desk, and sees, rotates and revokes only
the keys it issued itself."""
import pytest
import httpx

from research_agent.service.app import CloudSettings, create_app
from research_agent.service.clients import FileClients

ORIGIN = "https://research.example.test"


@pytest.fixture
def clients(tmp_path):
    return FileClients(tmp_path / "keys" / "clients.json")


@pytest.fixture
async def client(tmp_path, clients):
    app = create_app(tmp_path / "data", "service-value", None, cloud=CloudSettings(origin=ORIGIN, clients=clients))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN, headers={"x-forwarded-proto": "https"}) as c:
        yield c
    await app.state.runtime.close()


async def call(c, key, name, arguments=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}}
    return (await c.post("/mcp", json=body, headers={"Authorization": "Bearer " + key})).json()["result"]


def test_the_store_keeps_a_desk_inside_its_grants_ceiling_and_own_keys(clients):
    desk = clients.add_desk("ania", ["read", "research.run"], 20)
    assert clients.verify(desk)["scopes"] == ["keys.issue"]
    key = clients.desk_issue("ania", "team-bot", ["read", "research.run"], 15)
    assert clients.verify(key) == {"name": "team-bot", "scopes": ["read", "research.run"], "dailyUsd": 15.0}
    with pytest.raises(ValueError, match="may give read, research.run"):
        clients.desk_issue("ania", "x", ["tools.call"])
    with pytest.raises(ValueError, match="at most 20"):
        clients.desk_issue("ania", "y", ["read"], 25)
    with pytest.raises(ValueError, match="at least 10"):
        clients.desk_issue("ania", "z", ["read"], 5)
    clients.add("operators-own", ["read"])
    with pytest.raises(KeyError):
        clients.desk_revoke("ania", "operators-own")
    with pytest.raises(KeyError):
        clients.desk_issue("team-bot", "w", ["read"])  # an ordinary key is not a desk
    assert [c["name"] for c in clients.desk_list("ania")] == ["team-bot"]
    new = clients.desk_rotate("ania", "team-bot")
    assert clients.verify(key) is None and clients.verify(new)["name"] == "team-bot"
    clients.desk_revoke("ania", "team-bot")
    assert clients.verify(new) is None


def test_a_desk_gives_read_keys_at_the_floor_by_default(clients):
    clients.add_desk("steward")
    with pytest.raises(ValueError):
        clients.desk_issue("steward", "a", ["research.run"])
    assert clients.verify(clients.desk_issue("steward", "b"))["scopes"] == ["read"]


async def test_the_desk_tools_over_mcp_and_a_desk_key_reads_no_data(client, clients):
    desk = clients.add_desk("ania", ["read", "research.run", "tools.call"], 10)
    tools = (await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                               headers={"Authorization": "Bearer " + desk})).json()["result"]["tools"]
    assert {"client.issue", "client.rotate", "client.revoke", "client.list"} <= {t["name"] for t in tools}
    issued = (await call(client, desk, "client.issue", {"name": "esim-vm", "scopes": ["read", "research.run"]}))["structuredContent"]
    assert issued["shownOnce"] and issued["key"].startswith("prc_") and issued["dailyUsd"] == 10
    assert clients.verify(issued["key"])["scopes"] == ["read", "research.run"]
    listed = (await call(client, desk, "client.list"))["structuredContent"]["clients"]
    assert [c["name"] for c in listed] == ["esim-vm"] and "key" not in listed[0]
    assert (await call(client, desk, "research.list_runbooks"))["isError"], "a desk key reads no data"
    assert (await call(client, issued["key"], "client.list"))["isError"], "an ordinary key has no desk"
    assert (await call(client, desk, "client.revoke", {"name": "esim-vm"}))["structuredContent"]["revoked"]
    assert clients.verify(issued["key"]) is None
