"""Client keys of the cloud instance (B-099 M3, REQ-5): printed once, SHA-256 only,
scoped, rotated and revoked one by one, on a 0600 file and on Postgres."""
import hashlib
import json
import os
import sqlite3
import stat

import pytest

from research_agent.service.clients import FileClients, PostgresClients, SCOPES


class SqliteAsPostgres:
    """A DB-API connection that speaks psycopg's `%s` paramstyle over SQLite."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:")

    def cursor(self):
        db = self.db

        class Cursor:
            def execute(self, sql, params=()):
                self._cur = db.execute(sql.replace("%s", "?").replace("BYTEA", "BLOB").replace("TIMESTAMPTZ", "TEXT"), params)
                return self

            def fetchone(self):
                return self._cur.fetchone()

            def fetchall(self):
                return self._cur.fetchall()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return Cursor()

    def commit(self):
        self.db.commit()


@pytest.fixture(params=["file", "postgres"])
def clients(request, tmp_path):
    if request.param == "file":
        return FileClients(tmp_path / "clients.json")
    connection = SqliteAsPostgres()
    return PostgresClients(lambda: connection)


def test_add_prints_once_and_stores_only_the_hash(clients, tmp_path):
    key = clients.add("anna", ["read", "tools.call"])
    assert key.startswith("prc_") and len(key) > 40
    listed = clients.list()
    assert [c["name"] for c in listed] == ["anna"]
    assert key not in json.dumps(listed)
    assert listed[0]["scopes"] == ["read", "tools.call"]
    assert listed[0]["prefix"] == key[:12]
    if isinstance(clients, FileClients):
        raw = (tmp_path / "clients.json").read_text()
        assert key not in raw and hashlib.sha256(key.encode()).hexdigest() in raw


def test_verify_answers_the_name_and_scopes(clients):
    key = clients.add("anna", ["read"])
    assert clients.verify(key) == {"name": "anna", "scopes": ["read"]}
    assert clients.verify(key + "x") is None
    assert clients.verify("") is None
    assert clients.verify("Bearer " + key) is None


def test_rotate_replaces_and_revoke_refuses_at_once(clients):
    old = clients.add("anna", ["read"])
    other = clients.add("boris", ["read"])
    new = clients.rotate("anna")
    assert new != old and clients.verify(old) is None and clients.verify(new)["name"] == "anna"
    clients.revoke("anna")
    assert clients.verify(new) is None
    assert clients.verify(other)["name"] == "boris"
    assert [c["revokedAt"] is not None for c in clients.list() if c["name"] == "anna"] == [True]


def test_refusals(clients):
    clients.add("anna", ["read"])
    with pytest.raises(ValueError):
        clients.add("anna", ["read"])
    with pytest.raises(ValueError):
        clients.add("Anna Smith", ["read"])
    with pytest.raises(ValueError):
        clients.add("boris", ["admin"])
    with pytest.raises(ValueError):
        clients.add("boris", [])
    with pytest.raises(KeyError):
        clients.revoke("nobody")
    with pytest.raises(KeyError):
        clients.rotate("nobody")


def test_a_revoked_name_cannot_be_rotated_back(clients):
    clients.add("anna", ["read"])
    clients.revoke("anna")
    with pytest.raises(KeyError):
        clients.rotate("anna")


def test_scopes_are_the_three_capabilities_groups():
    assert SCOPES == ("read", "research.run", "tools.call")


def test_file_store_is_0600(tmp_path):
    FileClients(tmp_path / "clients.json").add("anna", ["read"])
    assert stat.S_IMODE(os.stat(tmp_path / "clients.json").st_mode) == 0o600
