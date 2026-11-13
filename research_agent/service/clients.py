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
#: A paid job starts on its own when it fits the key's daily ceiling, else it waits for the operator (B-100); a job of an
#: interactive key starts on its own whatever it costs (K1).
SCOPES = ("read", "research.run", "tools.call")
#: Every key carries a daily USD ceiling of at least this, 10 by default: the operator's word recorded in the agents
#: database (intake in-20261112-996c34, research template 1.6.0). A smaller one is refused.
DAILY_FLOOR_USD = 10.0
#: K1 (the operator's word of 2026-11-13, DEC-0074 of the Appvillis keys plan): a key is `interactive` (a person, or an
#: agent a person calls in that moment) and has no daily ceiling, or `automated` (a pipeline, a schedule) and keeps its
#: ceiling. A key without a class reads as `automated`: it behaves as before until it is reissued.
KEY_CLASSES = ("interactive", "automated")
DEFAULT_CLASS = "automated"
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


#: The issuing desk (research template 1.6.0, B-121): a team's key steward holds a desk key with this scope. It calls
#: only the desk tools, issues keys within the grants and the ceiling the operator's tool gave the desk (read keys and
#: the floor by default), and sees, rotates and revokes only the keys it issued itself, never a desk key.
DESK_SCOPE = "keys.issue"
DESK_DEFAULT_GRANTS = ("read",)


def _ceiling(daily_usd) -> float:
    try:
        value = float(daily_usd)
    except (TypeError, ValueError):
        raise ValueError("daily ceiling: a number of USD") from None
    if not value >= DAILY_FLOOR_USD or value > 1000:
        raise ValueError(f"daily ceiling: at least {DAILY_FLOOR_USD:g} and at most 1000 USD per UTC day")
    return value


def _classed(key_class, daily_usd) -> tuple[str, float | None]:
    """(class, ceiling): an interactive key carries no ceiling (None, never 0); an automated one carries its ceiling."""
    key_class = key_class or DEFAULT_CLASS
    if key_class not in KEY_CLASSES:
        raise ValueError("key class: " + " or ".join(KEY_CLASSES))
    if key_class == "interactive":
        if daily_usd is not None:
            raise ValueError("an interactive key has no daily ceiling; issue it as automated to give it one")
        return key_class, None
    return key_class, _ceiling(DAILY_FLOOR_USD if daily_usd is None else daily_usd)


def _ceiling_of(key_class, stored) -> float | None:
    """What a record's ceiling reads as: None for an interactive key, else never below the floor."""
    if (key_class or DEFAULT_CLASS) == "interactive":
        return None
    return max(float(DAILY_FLOOR_USD if stored is None else stored), DAILY_FLOOR_USD)


def _usable(key) -> bool:
    return isinstance(key, str) and key.startswith(PREFIX) and 20 < len(key) < 200


class DeskMixin:
    """The desk on top of a store's own primitives: `_get(name)`, `_insert(name, record)` and `_set(name, **fields)`.
    A record carries `issuedBy` (the desk that issued it, or None for the operator's tool) and, for a desk key,
    `grants` and `maxDailyUsd`."""

    def add_desk(self, name: str, grants=DESK_DEFAULT_GRANTS, max_daily_usd: float = DAILY_FLOOR_USD) -> str:
        """The operator's own tool gives a steward a desk key; `grants` and `max_daily_usd` bound what it may issue."""
        grants = _check(name, grants)
        max_daily_usd = _ceiling(max_daily_usd)
        if self._get(name) is not None:
            raise ValueError(f"client {name} exists; rotate it or choose another name")
        key = _new_key()
        self._insert(name, {"key": key, "scopes": [DESK_SCOPE], "dailyUsd": DAILY_FLOOR_USD, "issuedBy": None,
                            "grants": grants, "maxDailyUsd": max_daily_usd, "keyClass": DEFAULT_CLASS})
        return key

    def _desk(self, desk: str) -> dict:
        record = self._get(desk)
        if record is None or record["revokedAt"] or DESK_SCOPE not in record["scopes"]:
            raise KeyError("not-a-desk")
        return record

    def _issued(self, desk: str, name: str) -> dict:
        record = self._get(name)
        if record is None or record.get("issuedBy") != desk:
            raise KeyError("unknown-client")  # another desk's or the operator's key reads as unknown
        return record

    def desk_issue(self, desk: str, name: str, scopes=None, daily_usd: float | None = None,
                   key_class: str | None = None) -> str:
        d = self._desk(desk)
        scopes = _check(name, scopes or ["read"])
        if not set(scopes) <= set(d["grants"]):
            raise ValueError("scopes: this desk may give " + ", ".join(d["grants"]))
        key_class, daily_usd = _classed(key_class, daily_usd)
        if daily_usd is not None and daily_usd > d["maxDailyUsd"]:
            raise ValueError(f"daily ceiling: this desk may give at most {d['maxDailyUsd']:g} USD per UTC day")
        if self._get(name) is not None:
            raise ValueError(f"client {name} exists; choose another name")
        key = _new_key()
        self._insert(name, {"key": key, "scopes": scopes, "dailyUsd": daily_usd, "issuedBy": desk, "grants": None,
                            "maxDailyUsd": None, "keyClass": key_class})
        return key

    def desk_rotate(self, desk: str, name: str) -> str:
        self._desk(desk)
        if self._issued(desk, name)["revokedAt"]:
            raise KeyError("unknown-client")
        return self.rotate(name)

    def desk_revoke(self, desk: str, name: str) -> None:
        self._desk(desk)
        self._issued(desk, name)
        self.revoke(name)

    def desk_list(self, desk: str) -> list[dict]:
        self._desk(desk)
        return [c for c in self.list() if c.get("issuedBy") == desk]


class FileClients(DeskMixin):
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

    def _get(self, name: str) -> dict | None:
        record = self._load().get(name)
        return None if record is None else {"name": name, **record}

    def _insert(self, name: str, record: dict) -> None:
        data = self._load()
        key = record.pop("key")
        data[name] = {"sha256": _hash(key), "prefix": key[:12], "createdAt": _now(), "revokedAt": None, **record}
        self._write(data)

    def add(self, name: str, scopes, daily_usd: float | None = None, key_class: str | None = None) -> str:
        scopes = _check(name, scopes)
        key_class, daily_usd = _classed(key_class, daily_usd)
        data = self._load()
        if name in data:
            raise ValueError(f"client {name} exists; rotate it or choose another name")
        key = _new_key()
        data[name] = {"sha256": _hash(key), "scopes": scopes, "prefix": key[:12], "createdAt": _now(), "revokedAt": None,
                      "dailyUsd": daily_usd, "keyClass": key_class}
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
        if data[name].get("keyClass") == "interactive":
            raise ValueError(f"{name} is an interactive key and has no daily ceiling; issue an automated key to limit it")
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
                 "dailyUsd": _ceiling_of(c.get("keyClass"), c.get("dailyUsd")), "keyClass": c.get("keyClass") or DEFAULT_CLASS,
                 "issuedBy": c.get("issuedBy")} for n, c in sorted(self._load().items())]

    def verify(self, key) -> dict | None:
        if not _usable(key):
            return None
        wanted = _hash(key)
        for name, c in self._load().items():
            if not c["revokedAt"] and secrets.compare_digest(c["sha256"], wanted):
                return {"name": name, "scopes": c["scopes"], "dailyUsd": _ceiling_of(c.get("keyClass"), c.get("dailyUsd")),
                        "keyClass": c.get("keyClass") or DEFAULT_CLASS}
        return None


class PostgresClients(DeskMixin):
    """Clients in table `prowl_research_clients`; `connect` returns a DB-API connection
    with psycopg's `%s` paramstyle."""

    TABLE = """CREATE TABLE IF NOT EXISTS prowl_research_clients (
        name TEXT PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL, scopes TEXT NOT NULL, prefix TEXT NOT NULL,
        created_at TEXT NOT NULL, revoked_at TEXT)"""
    #: Added in 0.5.0 (B-100): a key created before carries the floor. Run only when the column is missing: an ALTER
    #: waits for an exclusive lock, so every new process would queue behind the web dyno's connection (B-119).
    CEILING = f"ALTER TABLE prowl_research_clients ADD COLUMN daily_usd DOUBLE PRECISION NOT NULL DEFAULT {DAILY_FLOOR_USD}"
    HAS_COLUMN = ("SELECT 1 FROM information_schema.columns WHERE table_name = 'prowl_research_clients'"
                  " AND column_name = %s")
    #: Added in 0.6.0 (B-121, the issuing desk); each only when missing (B-119).
    DESK_COLUMNS = (("issued_by", "TEXT"), ("grants", "TEXT"), ("max_daily_usd", "DOUBLE PRECISION"),
                    # Added in 0.6.3 (K1): NULL reads as automated. `daily_usd` stays NOT NULL; an interactive key keeps
                    # the floor there and reads it as no ceiling.
                    ("key_class", "TEXT"))

    def __init__(self, connect: Callable):
        self.connect = connect
        self._ready = False

    def _db(self):
        connection = self.connect()
        if not self._ready:
            with connection.cursor() as cur:
                cur.execute(self.TABLE)
                if not cur.execute(self.HAS_COLUMN, ("daily_usd",)).fetchone():
                    cur.execute(self.CEILING)
                for column, kind in self.DESK_COLUMNS:
                    if not cur.execute(self.HAS_COLUMN, (column,)).fetchone():
                        cur.execute(f"ALTER TABLE prowl_research_clients ADD COLUMN {column} {kind}")
            connection.commit()
            self._ready = True
        return connection

    def _get(self, name: str) -> dict | None:
        db = self._db()
        with db.cursor() as cur:
            row = cur.execute("SELECT name, scopes, daily_usd, revoked_at, issued_by, grants, max_daily_usd, key_class"
                              " FROM prowl_research_clients WHERE name=%s", (name,)).fetchone()
        db.commit()
        if row is None:
            return None
        return {"name": row[0], "scopes": json.loads(row[1]), "dailyUsd": _ceiling_of(row[7], row[2]), "revokedAt": row[3],
                "issuedBy": row[4], "grants": json.loads(row[5]) if row[5] else None, "maxDailyUsd": row[6],
                "keyClass": row[7] or DEFAULT_CLASS}

    def _insert(self, name: str, record: dict) -> None:
        db = self._db()
        key = record["key"]
        with db.cursor() as cur:
            cur.execute("INSERT INTO prowl_research_clients(name, sha256, scopes, prefix, created_at, revoked_at, daily_usd, issued_by,"
                        " grants, max_daily_usd, key_class) VALUES (%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s)",
                        (name, _hash(key), json.dumps(record["scopes"]), key[:12], _now(),
                         DAILY_FLOOR_USD if record["dailyUsd"] is None else record["dailyUsd"], record["issuedBy"],
                         json.dumps(record["grants"]) if record["grants"] else None, record["maxDailyUsd"],
                         record.get("keyClass") or DEFAULT_CLASS))
        db.commit()

    def add(self, name: str, scopes, daily_usd: float | None = None, key_class: str | None = None) -> str:
        scopes = _check(name, scopes)
        key_class, daily_usd = _classed(key_class, daily_usd)
        db = self._db()
        with db.cursor() as cur:
            if cur.execute("SELECT 1 FROM prowl_research_clients WHERE name=%s", (name,)).fetchone():
                raise ValueError(f"client {name} exists; rotate it or choose another name")
            key = _new_key()
            cur.execute("INSERT INTO prowl_research_clients(name, sha256, scopes, prefix, created_at, revoked_at, daily_usd, key_class)"
                        " VALUES (%s,%s,%s,%s,%s,NULL,%s,%s)", (name, _hash(key), json.dumps(scopes), key[:12], _now(),
                                                               DAILY_FLOOR_USD if daily_usd is None else daily_usd, key_class))
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
            row = cur.execute("SELECT key_class FROM prowl_research_clients WHERE name=%s AND revoked_at IS NULL", (name,)).fetchone()
            if not row:
                raise KeyError(f"no active client {name}")
            if row[0] == "interactive":
                raise ValueError(f"{name} is an interactive key and has no daily ceiling; issue an automated key to limit it")
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
            rows = cur.execute("SELECT name, scopes, prefix, created_at, revoked_at, daily_usd, issued_by, key_class"
                               " FROM prowl_research_clients ORDER BY name").fetchall()
        db.commit()  # end the read transaction: an open one holds a lock that a later ALTER waits on (B-119)
        return [{"name": r[0], "scopes": json.loads(r[1]), "prefix": r[2], "createdAt": r[3], "revokedAt": r[4],
                 "dailyUsd": _ceiling_of(r[7], r[5]), "keyClass": r[7] or DEFAULT_CLASS, "issuedBy": r[6]} for r in rows]

    def verify(self, key) -> dict | None:
        if not _usable(key):
            return None
        db = self._db()
        with db.cursor() as cur:
            row = cur.execute("SELECT name, scopes, daily_usd, key_class FROM prowl_research_clients WHERE sha256=%s"
                              " AND revoked_at IS NULL", (_hash(key),)).fetchone()
        db.commit()  # the web dyno verifies every request: never leave it idle in a transaction (B-119)
        if row is None:
            return None
        return {"name": row[0], "scopes": json.loads(row[1]), "dailyUsd": _ceiling_of(row[3], row[2]),
                "keyClass": row[3] or DEFAULT_CLASS}


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
