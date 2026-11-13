"""B-104 (agents database pattern `client-keys` 1.1.0): keys stored under a pepper, reserved names refused, the
refusal reason kept for the log, and keys stored as a plain SHA-256 before 0.6.9 rewritten once on their next use."""
from __future__ import annotations

import json

import pytest

from research_agent.service.clients import (
    PEPPERED,
    FileClients,
    PostgresClients,
    _hash,
    from_env,
)

from test_cloud_clients import SqliteAsPostgres

PEPPER = "p" * 32


@pytest.fixture(params=["file", "postgres"])
def make(request, tmp_path):
    connection = SqliteAsPostgres()

    def build(pepper=PEPPER):
        if request.param == "file":
            return FileClients(tmp_path / "clients.json", pepper)
        return PostgresClients(lambda: connection, pepper)
    return build


def stored(clients, name):
    if isinstance(clients, FileClients):
        return json.loads(clients.path.read_text())[name]["sha256"]
    db = clients._db()
    with db.cursor() as cur:
        return cur.execute("SELECT sha256 FROM prowl_research_clients WHERE name=%s", (name,)).fetchone()[0]


def test_a_key_is_stored_under_the_pepper_and_verifies_only_with_it(make):
    clients = make()
    key = clients.add("anna", ["read"])
    assert stored(clients, "anna").startswith(PEPPERED) and stored(clients, "anna") != _hash(key)
    assert clients.verify(key)["name"] == "anna"
    assert make("q" * 32).verify(key) is None  # another pepper verifies nothing


def test_a_short_pepper_stops_the_store(tmp_path):
    with pytest.raises(ValueError, match="at least 16"):
        FileClients(tmp_path / "c.json", "short")


def test_a_plain_digest_from_before_is_rewritten_on_its_next_use(make):
    plain = make(None)
    key = plain.add("old", ["read"])
    assert stored(plain, "old") == _hash(key)
    peppered = make()
    assert peppered.verify(key)["name"] == "old"
    assert stored(peppered, "old").startswith(PEPPERED)
    assert peppered.verify(key)["name"] == "old"  # and keeps working


def test_reserved_names_are_refused(make):
    clients = make()
    for name in ("owner", "root", "operator", "system", "admin"):
        with pytest.raises(ValueError, match="reserved"):
            clients.add(name, ["read"])


def test_the_refusal_reason_is_typed(make):
    clients = make()
    key = clients.add("anna", ["read"])
    assert clients.refusal(key) is None
    assert clients.refusal("not-a-key") == "malformed"
    assert clients.refusal("prc_" + "x" * 40) == "unknown"
    clients.revoke("anna")
    assert clients.refusal(key) == "revoked" and clients.verify(key) is None


def test_the_cloud_store_needs_a_pepper(tmp_path):
    with pytest.raises(RuntimeError, match="CLIENT_KEY_PEPPER"):
        from_env(tmp_path, {"DATABASE_URL": "postgres://unused"})
    assert isinstance(from_env(tmp_path, {}), FileClients)
