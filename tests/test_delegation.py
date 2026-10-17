"""Wave 5 (FD-12): the callee side of Fabric delegation, by trust tier.

Tokens are minted here with a test Ed25519 key (the estate's issuer does not
publish keys yet — host-chain acceptance is KA-G03, wave 6)."""

from __future__ import annotations

import base64
import json
import time

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from research_agent.service.app import create_app
from research_agent.service.delegation import DelegationPolicy
from research_agent.service.protocol import EFFECTS

ISSUER = "urn:fabric:estate:test"
AUDIENCE = "prowl-research.default"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Estate:
    def __init__(self) -> None:
        self.key = Ed25519PrivateKey.generate()
        public = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.jwks = {"keys": [{"kty": "OKP", "crv": "Ed25519", "x": _b64(public), "kid": "k1",
                               "use": "sig", "alg": "EdDSA"}]}

    def token(self, *, aud=AUDIENCE, scope="research.run research.tutorial fabric.job.get", effect=("charge", "draft"),
              ttl=300, iat=None, kid="k1", sub="urn:person:operator", actor="caller-agent.default", key=None) -> str:
        now = int(time.time()) if iat is None else iat
        header = {"alg": "EdDSA", "typ": "fabric-delegation+jwt", "kid": kid}
        claims = {"iss": ISSUER, "sub": sub, "act": {"sub": actor}, "aud": aud, "scope": scope,
                  "effect": list(effect), "grant": ["urn:grant:test#1"], "project": "urn:project:test",
                  "iat": now, "exp": now + ttl, "jti": "jti-" + str(now) + "-abcdefghijkl"}
        signing = _b64(json.dumps(header).encode()) + "." + _b64(json.dumps(claims).encode())
        signature = (key or self.key).sign(signing.encode())
        return signing + "." + _b64(signature)


def _policy(estate: Estate) -> DelegationPolicy:
    return DelegationPolicy(issuer=ISSUER, jwks=estate.jwks, audience=AUDIENCE, effects=EFFECTS)


def _call(name, args, rid=1):
    return {"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": args}}


async def _post(app, body, headers, client_host="127.0.0.1"):
    transport = httpx.ASGITransport(app=app, client=(client_host, 5000))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:18764") as client:
        return await client.post("/mcp", json=body, headers=headers)


TUTORIAL = ("research.tutorial", {"idempotencyKey": "tut-1"})


@pytest.fixture
def estate():
    return Estate()


async def _result(app, headers, client_host="127.0.0.1", call=TUTORIAL):
    response = await _post(app, _call(*call), headers, client_host)
    return response.status_code, response.json()


async def test_a_good_token_is_accepted_and_its_chain_is_recorded(tmp_path, estate):
    app = create_app(tmp_path, "host", "agent", delegation=_policy(estate))
    status, body = await _result(app, {"Authorization": "Bearer " + estate.token()})
    assert status == 200 and body["result"]["isError"] is False
    job_id = body["result"]["structuredContent"]["job"]["id"]
    job = app.state.runtime.store.job(job_id)
    assert job["delegation"]["principal"] == "urn:person:operator"
    assert job["delegation"]["caller"] == "caller-agent.default"
    assert "jti" not in json.dumps(job["delegation"])  # never the token


@pytest.mark.parametrize("make,code", [
    (lambda e: e.token(aud="someone-else.default"), "wrong-audience"),
    (lambda e: e.token(iat=int(time.time()) - 2000, ttl=300), "token-expired"),
    (lambda e: e.token(key=Ed25519PrivateKey.generate()), "unauthenticated"),   # broken signature
    (lambda e: e.token(kid="k-unknown"), "unauthenticated"),                    # unknown key
    (lambda e: e.token(scope="research.run"), "scope-not-granted"),             # tutorial not in scope
    (lambda e: e.token(effect=("none",)), "effect-above-ceiling"),
])
async def test_a_bad_token_is_refused_with_the_contract_code(tmp_path, estate, make, code):
    app = create_app(tmp_path, "host", "agent", delegation=_policy(estate))
    status, body = await _result(app, {"Authorization": "Bearer " + make(estate)})
    assert status == 200 and body["result"]["isError"] is True
    assert body["result"]["structuredContent"]["error"]["code"] == code
    assert app.state.runtime.store.jobs() == []


async def test_the_own_agent_token_still_works_from_loopback(tmp_path, estate):
    app = create_app(tmp_path, "host", "agent", delegation=_policy(estate))
    status, body = await _result(app, {"Authorization": "Bearer agent"})
    assert body["result"]["isError"] is False  # T0: no delegation required
    job = app.state.runtime.store.job(body["result"]["structuredContent"]["job"]["id"])
    assert job["delegation"] is None


async def test_a_token_beside_the_own_token_is_still_verified(tmp_path, estate):
    app = create_app(tmp_path, "host", "agent", delegation=_policy(estate))
    bad = estate.token(aud="someone-else.default")
    status, body = await _result(app, {"Authorization": "Bearer agent", "Fabric-Delegation": bad})
    assert body["result"]["structuredContent"]["error"]["code"] == "wrong-audience"


async def test_with_no_trusted_issuer_a_presented_token_is_refused(tmp_path, estate):
    app = create_app(tmp_path, "host", "agent", delegation=DelegationPolicy(issuer=None, jwks=None,
                                                                           audience=AUDIENCE, effects=EFFECTS))
    status, body = await _result(app, {"Authorization": "Bearer " + estate.token()})
    assert body["result"]["structuredContent"]["error"]["code"] == "issuer-unavailable"
    status, body = await _result(app, {"Authorization": "Bearer agent"})
    assert body["result"]["isError"] is False  # the own token without a delegation token is fine on loopback


async def test_off_the_machine_the_own_token_alone_is_not_enough(tmp_path, estate):
    app = create_app(tmp_path, "host", "agent", delegation=_policy(estate))
    status, body = await _result(app, {"Authorization": "Bearer agent"}, client_host="203.0.113.7")
    assert body["result"]["structuredContent"]["error"]["code"] == "unauthenticated"  # T2 needs a token
    status, body = await _result(app, {"Authorization": "Bearer agent", "Fabric-Delegation": estate.token()},
                                 client_host="203.0.113.7")
    assert body["result"]["isError"] is False


async def test_no_credential_at_all_is_a_401(tmp_path, estate):
    app = create_app(tmp_path, "host", "agent", delegation=_policy(estate))
    response = await _post(app, _call(*TUTORIAL), {})
    assert response.status_code == 401


async def test_a_delegated_caller_sees_only_its_own_jobs(tmp_path, estate):
    app = create_app(tmp_path, "host", "agent", delegation=_policy(estate))
    _, mine = await _result(app, {"Authorization": "Bearer " + estate.token()})
    job_id = mine["result"]["structuredContent"]["job"]["id"]
    other = estate.token(actor="another-agent.default")
    _, body = await _result(app, {"Authorization": "Bearer " + other}, call=("fabric.job.get", {"id": job_id}))
    assert body["result"]["isError"] is True and "scope-not-granted" in json.dumps(body)
    _, body = await _result(app, {"Authorization": "Bearer " + estate.token()}, call=("fabric.job.get", {"id": job_id}))
    assert body["result"]["isError"] is False


def test_the_well_known_document_declares_delegation_when_configured(tmp_path, estate):
    configured = create_app(tmp_path / "a", "host", "agent", delegation=_policy(estate))
    plain = create_app(tmp_path / "b", "host", "agent",
                       delegation=DelegationPolicy(issuer=None, jwks=None, audience=AUDIENCE, effects=EFFECTS))
    import asyncio

    async def well_known(app):
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 5000))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:18764") as client:
            return (await client.get("/.well-known/fabric-service")).json()

    assert asyncio.run(well_known(configured))["auth"]["delegation"]["issuer"] == ISSUER
    assert "auth" not in asyncio.run(well_known(plain))


def test_binding_beyond_loopback_needs_delegation(tmp_path):
    from research_agent.service.cli import check_bind

    assert check_bind("127.0.0.1", {}) is None
    assert "refusing to bind 0.0.0.0" in check_bind("0.0.0.0", {})
    jwks = tmp_path / "jwks.json"
    jwks.write_text(json.dumps(Estate().jwks))
    assert check_bind("0.0.0.0", {"RESEARCH_DELEGATION_ISSUER": ISSUER, "RESEARCH_DELEGATION_JWKS": str(jwks)}) is None
