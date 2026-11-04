"""State of the cloud instance in Postgres (B-099 M4, R-9).

A Heroku dyno's disk is wiped at every restart, so the data root (the SQLite job
store and `runs/`) is kept as a snapshot: restored before the store opens, saved when
it changed (checked every 30 s) and at shutdown. Each snapshot carries its SHA-256; a
damaged one is skipped for the next older, never unpacked. Three are kept."""
from __future__ import annotations

import gzip
import hashlib
import io
import logging
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

log = logging.getLogger("research_agent.service.snapshot")
KEEP = 3
#: Never in a snapshot: the instance lock, half-written files, SQLite's side files
#: (the database is copied through the backup API instead) and the local key file.
SKIP_SUFFIXES = (".lock", ".tmp", "-wal", "-shm", "-journal")
SKIP_NAMES = {"service.sqlite3", "clients.json", "host.token", "agent.token"}


def pack(root: Path) -> bytes:
    root = Path(root)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        database = root / "service.sqlite3"
        if database.exists():
            with tempfile.TemporaryDirectory() as tmp:
                copy = Path(tmp) / "service.sqlite3"
                source, target = sqlite3.connect(database), sqlite3.connect(copy)
                try:
                    source.backup(target)
                finally:
                    source.close()
                    target.close()
                tar.add(copy, "service.sqlite3", filter=_stable)
        for path in sorted(root.rglob("*")):
            name = path.relative_to(root).as_posix()
            if path.is_dir() or path.is_symlink() or path.name in SKIP_NAMES or path.name.endswith(SKIP_SUFFIXES):
                continue
            tar.add(path, name, filter=_stable)
    # No timestamps anywhere: an unchanged root packs to the same bytes, so it is not saved again.
    return gzip.compress(buffer.getvalue(), mtime=0)


def _stable(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mode = 0o600
    info.mtime = 0
    info.pax_headers = {}
    return info


def unpack(body: bytes, root: Path) -> None:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tar:
        members = tar.getmembers()
        for m in members:
            p = PurePosixPath(m.name)
            if p.is_absolute() or ".." in p.parts or not (m.isfile() or m.isdir()):
                raise ValueError(f"snapshot member refused: {m.name}")
        tar.extractall(root, members=members, filter="data")


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class Snapshots:
    """Table `prowl_research_snapshot`; `connect` returns a DB-API connection with `%s`."""

    TABLE = """CREATE TABLE IF NOT EXISTS prowl_research_snapshot (
        taken_at TEXT PRIMARY KEY, sha256 TEXT NOT NULL, size INTEGER NOT NULL, body BYTEA NOT NULL)"""

    def __init__(self, connect: Callable):
        self.connect = connect
        self.last = None

    def _db(self):
        db = self.connect()
        with db.cursor() as cur:
            cur.execute(self.TABLE)
        db.commit()
        return db

    def save(self, root: Path) -> bool:
        """Saves the data root when it changed since the last save; answers whether it did."""
        body = pack(root)
        sha = digest(body)
        if sha == self.last:
            return False
        db = self._db()
        taken = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        with db.cursor() as cur:
            cur.execute("INSERT INTO prowl_research_snapshot(taken_at, sha256, size, body) VALUES (%s,%s,%s,%s)", (taken, sha, len(body), body))
            old = cur.execute("SELECT taken_at FROM prowl_research_snapshot ORDER BY taken_at DESC").fetchall()[KEEP:]
            for (stamp,) in old:
                cur.execute("DELETE FROM prowl_research_snapshot WHERE taken_at=%s", (stamp,))
        db.commit()
        self.last = sha
        log.info("event=snapshot.saved size=%s sha256=%s", len(body), sha[:12])
        return True

    def restore(self, root: Path) -> str | None:
        """Unpacks the newest intact snapshot into an empty data root; answers its stamp."""
        with self._db().cursor() as cur:
            rows = cur.execute("SELECT taken_at, sha256, body FROM prowl_research_snapshot ORDER BY taken_at DESC").fetchall()
        for stamp, sha, body in rows:
            body = bytes(body)
            if digest(body) != sha:
                log.warning("event=snapshot.damaged taken_at=%s", stamp)
                continue
            unpack(body, root)
            self.last = sha
            log.info("event=snapshot.restored taken_at=%s", stamp)
            return stamp
        return None


def from_env(environ) -> Snapshots | None:
    url = environ.get("DATABASE_URL")
    if not url:
        return None
    import psycopg  # the `[cloud]` extra

    state = {}

    def connect():
        if state.get("c") is None or state["c"].closed:
            state["c"] = psycopg.connect(url)
        return state["c"]

    return Snapshots(connect)
