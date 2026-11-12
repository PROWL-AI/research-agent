"""Client keys of the cloud instance (B-099 M3, D16 K2).

One key per client: a teammate's Claude Code, a neighbouring agent, an integration.
A key is printed once by `add` or `rotate`; the store keeps only its SHA-256, its
scopes and its first characters for recognition. A revoked client stays listed and
can no longer be rotated back: a new key needs a new name. The Postgres store lets a
one-off dyno (`heroku run`) change the table the web dyno reads; the 0600 file is the
same interface for tests and for a cloud run without a database."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

#: What a key may do. `read`: list runbooks, read artifacts, run the free tutorial.
#: `research.run`: create research jobs. `tools.call`: create single Prowl tool jobs.
#: A paid job starts on its own when it fits the key's daily ceiling, else it waits for the operator (B-100).
SCOPES = ("read", "research.run", "tools.call")
#: Every key carries a daily USD ceiling of at least this, 10 by default: the operator's word recorded in the agents
#: database (intake in-20261112-996c34, research template 1.6.0). A smaller one is refused.
DAILY_FLOOR_USD = 10.0
PREFIX = "prc_"
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _new_key() -> str:
    return PREFIX + secrets.token_urlsafe(32)


def _check(name: str, scopes) -> list[str]:
    if not isinstance(name, str) or not NAME.match(name):
        raise ValueError("client name: lowercase letters, digits, '.', '_', '-', up to 64 characters")
    scopes = list(dict.fromkeys(scopes or []))
    if not scopes or any(s not in SCOPES for s in scopes):
        raise ValueError("scopes: one or more of " + ", ".join(SCOPES))
    return scopes


def _ceiling(daily_usd) -> float:
    try:
        value = float(daily_usd)
    except (TypeError, ValueError):
        raise ValueError("daily ceiling: a number of USD") from None
    if not value >= DAILY_FLOOR_USD or value > 1000:
        raise ValueError(f"daily ceiling: at least {DAILY_FLOOR_USD:g} and at most 1000 USD per UTC day")
    return value


def _usable(key) -> bool:
    return isinstance(key, str) and key.startswith(PREFIX) and 20 < len(key) < 200


class FileClients:
    """Clients in one 0600 JSON file."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, indent=1, sort_keys=True)
        os.replace(temp, self.path)
        self.path.chmod(0o600)

    def add(self, name: str, scopes, daily_usd: float = DAILY_FLOOR_USD) -> str:
        scopes, daily_usd = _check(name, scopes), _ceiling(daily_usd)
        data = self._load()
        if name in data:
            raise ValueError(f"client {name} exists; rotate it or choose another name")
        key = _new_key()
        data[name] = {"sha256": _hash(key), "scopes": scopes, "prefix": key[:12], "createdAt": _now(), "revokedAt": None,
                      "dailyUsd": daily_usd}
        self._write(data)
        return key

    def rotate(self, name: str) -> str:
        data = self._load()
        if name not in data or data[name]["revokedAt"]:
            raise KeyError(f"no active client {name}")
        key = _new_key()
        data[name].update(sha256=_hash(key), prefix=key[:12])
        self._write(data)
        return key

    def limit(self, name: str, daily_usd: float) -> None:
        daily_usd = _ceiling(daily_usd)
        data = self._load()
        if name not in data or data[name]["revokedAt"]:
            raise KeyError(f"no active client {name}")
        data[name]["dailyUsd"] = daily_usd
        self._write(data)

    def revoke(self, name: str) -> None:
        data = self._load()
        if name not in data:
            raise KeyError(f"no client {name}")
        data[name]["revokedAt"] = data[name]["revokedAt"] or _now()
        self._write(data)

    def list(self) -> list[dict]:
        return [{"name": n, "scopes": c["scopes"], "prefix": c["prefix"], "createdAt": c["createdAt"], "revokedAt": c["revokedAt"],
                 "dailyUsd": c.get("dailyUsd", DAILY_FLOOR_USD)} for n, c in sorted(self._load().items())]

    def verify(self, key) -> dict | None:
        if not _usable(key):
            return None
        wanted = _hash(key)
        for name, c in self._load().items():
            if not c["revokedAt"] and secrets.compare_digest(c["sha256"], wanted):
                return {"name": name, "scopes": c["scopes"], "dailyUsd": max(c.get("dailyUsd", DAILY_FLOOR_USD), DAILY_FLOOR_USD)}
        return None


class PostgresClients:
    """Clients in table `prowl_research_clients`; `connect` returns a DB-API connection
    with psycopg's `%s` paramstyle."""

    TABLE = """CREATE TABLE IF NOT EXISTS prowl_research_clients (
        name TEXT PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL, scopes TEXT NOT NULL, prefix TEXT NOT NULL,
        created_at TEXT NOT NULL, revoked_at TEXT)"""
    #: Added in 0.5.0 (B-100): a key created before carries the floor. Run only when the column is missing: an ALTER
    #: waits for an exclusive lock, so every new process would queue behind the web dyno's connection (B-119).
    CEILING = f"ALTER TABLE prowl_research_clients ADD COLUMN daily_usd DOUBLE PRECISION NOT NULL DEFAULT {DAILY_FLOOR_USD}"
    HAS_CEILING = ("SELECT 1 FROM information_schema.columns WHERE table_name = 'prowl_research_clients'"
                   " AND column_name = 'daily_usd'")

    def __init__(self, connect: Callable):
        self.connect = connect
        self._ready = False

    def _db(self):
        connection = self.connect()
        if not self._ready:
            with connection.cursor() as cur:
                cur.execute(self.TABLE)
                if not cur.execute(self.HAS_CEILING).fetchone():
                    cur.execute(self.CEILING)
            connection.commit()
            self._ready = True
        return connection

    def add(self, name: str, scopes, daily_usd: float = DAILY_FLOOR_USD) -> str:
        scopes, daily_usd = _check(name, scopes), _ceiling(daily_usd)
        db = self._db()
        with db.cursor() as cur:
            if cur.execute("SELECT 1 FROM prowl_research_clients WHERE name=%s", (name,)).fetchone():
                raise ValueError(f"client {name} exists; rotate it or choose another name")
            key = _new_key()
            cur.execute("INSERT INTO prowl_research_clients(name, sha256, scopes, prefix, created_at, revoked_at, daily_usd)"
                        " VALUES (%s,%s,%s,%s,%s,NULL,%s)", (name, _hash(key), json.dumps(scopes), key[:12], _now(), daily_usd))
        db.commit()
        return key

    def rotate(self, name: str) -> str:
        db = self._db()
        with db.cursor() as cur:
            if not cur.execute("SELECT 1 FROM prowl_research_clients WHERE name=%s AND revoked_at IS NULL", (name,)).fetchone():
                raise KeyError(f"no active client {name}")
            key = _new_key()
            cur.execute("UPDATE prowl_research_clients SET sha256=%s, prefix=%s WHERE name=%s", (_hash(key), key[:12], name))
        db.commit()
        return key

    def limit(self, name: str, daily_usd: float) -> None:
        daily_usd = _ceiling(daily_usd)
        db = self._db()
        with db.cursor() as cur:
            if not cur.execute("SELECT 1 FROM prowl_research_clients WHERE name=%s AND revoked_at IS NULL", (name,)).fetchone():
                raise KeyError(f"no active client {name}")
            cur.execute("UPDATE prowl_research_clients SET daily_usd=%s WHERE name=%s", (daily_usd, name))
        db.commit()

    def revoke(self, name: str) -> None:
        db = self._db()
        with db.cursor() as cur:
            if not cur.execute("SELECT 1 FROM prowl_research_clients WHERE name=%s", (name,)).fetchone():
                raise KeyError(f"no client {name}")
            cur.execute("UPDATE prowl_research_clients SET revoked_at=%s WHERE name=%s AND revoked_at IS NULL", (_now(), name))
        db.commit()

    def list(self) -> list[dict]:
        db = self._db()
        with db.cursor() as cur:
            rows = cur.execute("SELECT name, scopes, prefix, created_at, revoked_at, daily_usd FROM prowl_research_clients ORDER BY name").fetchall()
        db.commit()  # end the read transaction: an open one holds a lock that a later ALTER waits on (B-119)
        return [{"name": r[0], "scopes": json.loads(r[1]), "prefix": r[2], "createdAt": r[3], "revokedAt": r[4], "dailyUsd": r[5]}
                for r in rows]

    def verify(self, key) -> dict | None:
        if not _usable(key):
            return None
        db = self._db()
        with db.cursor() as cur:
            row = cur.execute("SELECT name, scopes, daily_usd FROM prowl_research_clients WHERE sha256=%s AND revoked_at IS NULL",
                              (_hash(key),)).fetchone()
        db.commit()  # the web dyno verifies every request: never leave it idle in a transaction (B-119)
        return {"name": row[0], "scopes": json.loads(row[1]), "dailyUsd": max(row[2], DAILY_FLOOR_USD)} if row else None


def from_env(root: Path, environ=os.environ):
    """Postgres when `DATABASE_URL` is set (Heroku), else a 0600 file in the data root."""
    url = environ.get("DATABASE_URL")
    if not url:
        return FileClients(Path(root) / "clients.json")
    import psycopg  # the `[cloud]` extra

    state = {}

    def connect():
        if state.get("c") is None or state["c"].closed:
            state["c"] = psycopg.connect(url, autocommit=False)
        return state["c"]

    return PostgresClients(connect)
