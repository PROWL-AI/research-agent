"""The cloud instance (B-099 M1-M3): its own https origin only, the well-known document
behind the service token, `/mcp` behind client keys with scopes, each client's jobs its
own, the `__Host-` session cookie. The local instance is covered by test_service.py."""
import pytest
import httpx

from research_agent.service.app import CloudSettings, create_app
from research_agent.service.clients import FileClients

ORIGIN = "https://research.example.test"


@pytest.fixture
def clients(tmp_path):
    return FileClients(tmp_path / "keys" / "clients.json")


@pytest.fixture
def app(tmp_path, clients):
    return create_app(tmp_path / "data", "service-value", None, cloud=CloudSettings(origin=ORIGIN, clients=clients))


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
                                 headers={"x-forwarded-proto": "https"}) as c:
        yield c
    await app.state.runtime.close()


def call(name, arguments, rid=1):
    return {"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


def bearer(key):
    return {"Authorization": "Bearer " + key}


async def test_only_its_own_https_origin(client):
    assert (await client.get("/.well-known/fabric-service", headers=bearer("service-value"))).status_code == 200
    assert (await client.get("/.well-known/fabric-service", headers=bearer("service-value") | {"x-forwarded-proto": "http"})).status_code == 403
    assert (await client.get("/.well-known/fabric-service", headers=bearer("service-value") | {"host": "evil.test"})).status_code == 403
    assert (await client.get("/.well-known/fabric-service", headers=bearer("service-value") | {"origin": "https://evil.test"})).status_code == 403


async def test_loopback_host_is_refused_in_the_cloud(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:18764") as c:
        assert (await c.get("/.well-known/fabric-service", headers=bearer("service-value"))).status_code == 403


async def test_well_known_needs_the_service_token(client):
    r = await client.get("/.well-known/fabric-service")
    assert r.status_code == 401 and r.content == b""
    health = (await client.get("/.well-known/fabric-service", headers=bearer("service-value"))).json()
    assert health["service"]["instance"] == "cloud"
    assert health["surfaces"]["mcp"]["auth"] == "own"


async def test_mcp_takes_only_client_keys(client, clients):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    assert (await client.post("/mcp", json=body)).status_code == 401
    assert (await client.post("/mcp", json=body, headers=bearer("service-value"))).status_code == 401
    assert (await client.post("/mcp", json=body, headers=bearer("prc_" + "x" * 43))).status_code == 401
    key = clients.add("anna", ["read"])
    r = await client.post("/mcp", json=body, headers=bearer(key))
    assert r.status_code == 200 and any(t["name"] == "research.run" for t in r.json()["result"]["tools"])
    clients.revoke("anna")
    assert (await client.post("/mcp", json=body, headers=bearer(key))).status_code == 401


async def test_scopes_gate_each_capability(client, clients):
    reader = clients.add("reader", ["read"])
    r = await client.post("/mcp", json=call("research.tools.call", {"idempotencyKey": "k", "tool": "google_news", "params": {"q": "x"}}), headers=bearer(reader))
    result = r.json()["result"]
    assert result["isError"] and result["structuredContent"]["error"]["code"] == "scope-not-granted"
    r = await client.post("/mcp", json=call("research.tutorial", {"idempotencyKey": "t"}), headers=bearer(reader))
    assert not r.json()["result"].get("isError")


async def test_a_clients_jobs_are_its_own(client, clients, app):
    anna = clients.add("anna", ["read"])
    boris = clients.add("boris", ["read"])
    r = await client.post("/mcp", json=call("research.tutorial", {"idempotencyKey": "same"}), headers=bearer(anna))
    job_id = r.json()["result"]["structuredContent"]["job"]["id"]
    job = app.state.store.job(job_id)
    assert job["delegation"]["principal"] == "client:anna" and job["delegation"]["tier"] == "client"
    # The same idempotency key from another client is another job, not anna's replay.
    r = await client.post("/mcp", json=call("research.tutorial", {"idempotencyKey": "same"}), headers=bearer(boris))
    assert r.json()["result"]["structuredContent"]["job"]["id"] != job_id
    r = await client.post("/mcp", json=call("fabric.job.get", {"id": job_id}), headers=bearer(boris))
    assert r.json()["result"]["isError"]
    r = await client.post("/mcp", json=call("fabric.job.get", {"id": job_id}), headers=bearer(anna))
    assert not r.json()["result"].get("isError")


async def test_paid_jobs_still_wait_for_the_operator(client, clients, app, monkeypatch):
    monkeypatch.setenv("PROWL_API_KEY", "p")
    key = clients.add("anna", ["tools.call"])
    r = await client.post("/mcp", json=call("research.tools.call", {"idempotencyKey": "k", "tool": "google_news", "params": {"q": "x"}}), headers=bearer(key))
    job_id = r.json()["result"]["structuredContent"]["job"]["id"]
    assert app.state.store.job(job_id)["status"] == "input_required"


async def test_session_cookie_is_host_prefixed_and_secure(client):
    r = await client.post("/fabric/v1/login-code", headers=bearer("service-value"))
    url = r.json()["url"]
    r = await client.get(url)
    assert r.status_code == 302
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("__Host-prowl_operator=") and "Secure" in cookie and "Path=/" in cookie and "Domain" not in cookie
    assert (await client.get("/api/state")).status_code == 200


async def test_the_page_and_identity_name_the_service(client):
    from research_agent.service.app import STATIC
    from research_agent.service.identity import SERVICE_ID, SERVICE_NAME
    r = await client.post("/fabric/v1/login-code", headers=bearer("service-value"))
    await client.get(r.json()["url"])
    page = (await client.get("/dashboard")).text
    # The original's page is its file, byte for byte; a copy's identity renames it.
    assert f"<title>{SERVICE_NAME} · Fabric</title>" in page and f"<footer>{SERVICE_NAME} <span>" in page
    if SERVICE_ID == "prowl-research":
        assert page == (STATIC / "index.html").read_text()
    health = (await client.get("/.well-known/fabric-service", headers=bearer("service-value"))).json()
    assert health["service"]["id"] == SERVICE_ID and health["service"]["name"] == SERVICE_NAME
