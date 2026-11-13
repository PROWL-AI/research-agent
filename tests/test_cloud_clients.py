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

    alters = 0

    def __init__(self):
        self.db = sqlite3.connect(":memory:")

    def cursor(self):
        db = self.db

        class Cursor:
            def execute(self, sql, params=()):
                sql = sql.replace("%s", "?").replace("BYTEA", "BLOB").replace("TIMESTAMPTZ", "TEXT")
                if "information_schema.columns" in sql:  # Postgres catalogue; SQLite answers from its pragma
                    sql = "SELECT 1 FROM pragma_table_info('prowl_research_clients') WHERE name = ?"
                if sql.startswith("ALTER"):
                    SqliteAsPostgres.alters += 1
                if "ADD COLUMN IF NOT EXISTS" in sql:  # Postgres only; SQLite says "duplicate column" instead
                    try:
                        self._cur = db.execute(sql.replace("ADD COLUMN IF NOT EXISTS", "ADD COLUMN"), params)
                    except sqlite3.OperationalError as exc:
                        if "duplicate column" not in str(exc):
                            raise
                    return self
                self._cur = db.execute(sql, params)
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


def test_verify_answers_the_name_scopes_and_daily_ceiling(clients):
    key = clients.add("anna", ["read"])
    assert clients.verify(key) == {"name": "anna", "scopes": ["read"], "dailyUsd": 10.0}
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


def test_reads_never_leave_a_transaction_open_and_the_column_is_added_once():
    """B-119: the web dyno verified keys inside a transaction it never ended, and the 0.5.0 ALTER of every new process
    (a one-off `client add`) waited for that transaction forever."""
    connection = SqliteAsPostgres()
    clients = PostgresClients(lambda: connection)
    key = clients.add("anna", ["read"])
    SqliteAsPostgres.alters = 0
    assert clients.verify(key)["name"] == "anna"
    assert not connection.db.in_transaction
    clients.list()
    assert not connection.db.in_transaction
    PostgresClients(lambda: connection).list()  # a second process on the same table
    assert SqliteAsPostgres.alters == 0, "the column exists: no ALTER, no exclusive lock"


def test_a_desk_on_either_store(clients):
    """B-121 on both stores: the desk issues within its grants and sees only its own keys."""
    clients.add_desk("ania", ["read", "research.run"], 20)
    key = clients.desk_issue("ania", "team-bot", ["research.run"], 12)
    assert clients.verify(key) == {"name": "team-bot", "scopes": ["research.run"], "dailyUsd": 12.0}
    clients.add("other", ["read"])
    assert [c["name"] for c in clients.desk_list("ania")] == ["team-bot"]
    with pytest.raises(KeyError):
        clients.desk_rotate("ania", "other")
