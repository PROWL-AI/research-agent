"""Spend guard and spend ledger: reserve the worst case before every paid call, settle to the real cost after.

Pattern `spend-ledger`, version 1.3.0 (PassionCode agents database, shared pattern B-1, B-11, B-12).

Guarantees:
- `reserve` runs in ONE immediate SQLite transaction: every ceiling that applies (the month's stop just under the
  provider key's own limit, the day, and any scoped ceiling per key, app, lane, run) must hold the settled spend plus
  every open reservation plus this call's worst case, so two processes can never race over a ceiling;
- `settle` writes the actual cost; a call that ran is never recorded at 0 unless the provider confirmed 0 (no cost,
  or an unconfirmed one, keeps the worst case); `release` frees a call that provably never left (evidence required);
- an unknown outcome counts in full and blocks a retry of the same operation until reconciled with evidence;
- months are calendar months in UTC, days UTC days, read from an injected clock (a naive clock is refused);
- a ceiling that is reached returns a typed `Decision` with an `Ask`: "double or keep", no recommended option; only
  the operator doubles, anyone keeps; a keep holds for that period at that value; every answer is recorded;
- the store survives a restart and keeps an append-only, hash-chained journal of every change. It is chosen at
  construction: `storage="sqlite"` (the default, one database file) or `storage="jsonl"`, the light store of a small
  agent: one JSON object per line, one line per transaction, fsynced before the answer, every line chained to the one
  before, writers serialized by a lock file next to it (`<path>.lock`); a torn last line (a crash in the middle of an
  append) is ignored and reported, and the next write drops it and journals `ledger.torn`. Both stores give the same
  answers: the guard runs the same queries over the journal replayed into an in-memory index.

A template injects: the `Policy` (key limit, stop, ceilings, scopes), the database path, a `clock` returning an
aware datetime, a `notify(event)` callback, and optional readers of other consumers of the same key and of the
provider's own usage figure. Money is `Decimal`, stored as integer micro-USD; floats are converted through `str`.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Callable, Mapping, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - not POSIX: the jsonl store refuses to start
    fcntl = None

__all__ = ["money", "Ceiling", "OtherConsumer", "Velocity", "Policy", "Ask", "Decision", "SpendLedger",
           "policy_problems", "policy_warnings", "STORAGES"]

_MICRO = Decimal("0.000001")
PERIODS = ("day", "month", "total", "24h", "30d")
ROLLING_S = {"24h": 86400, "30d": 30 * 86400}  # rolling windows: the last 24 h or 30 days, not calendar periods
DRIFT_RATIO = Decimal("1.5")
WARN_SHARE = Decimal("0.8")
COUNTING = ("reserved", "unknown")
STORAGES = ("sqlite", "jsonl")
_COLUMNS = {
    "calls": ("rid", "call_id", "op_key", "label", "scopes", "day", "month", "ts", "worst", "cost", "confirmed",
              "counted", "state", "note"),
    "overrides": ("name", "micros"),
    "asks": ("id", "ceiling", "period", "period_key", "limit_m", "state", "opened_at", "answered_by", "answered_at"),
    "halts": ("cause", "by", "at"),
    "readings": ("name", "month", "micros"),
    "once": ("key",),
    "journal": ("seq", "at", "kind", "ref", "body", "prev", "hash"),
}
_LINE_KEYS = {"n", "ops", "prev", "h"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (rid INTEGER PRIMARY KEY, call_id TEXT NOT NULL, op_key TEXT NOT NULL, label TEXT,
  scopes TEXT NOT NULL, day TEXT NOT NULL, month TEXT NOT NULL, ts REAL NOT NULL, worst INTEGER NOT NULL,
  cost INTEGER, confirmed INTEGER NOT NULL DEFAULT 0, counted INTEGER NOT NULL, state TEXT NOT NULL, note TEXT);
CREATE INDEX IF NOT EXISTS calls_month ON calls (month);
CREATE INDEX IF NOT EXISTS calls_call ON calls (call_id);
CREATE INDEX IF NOT EXISTS calls_op ON calls (op_key);
CREATE TABLE IF NOT EXISTS overrides (name TEXT PRIMARY KEY, micros INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS asks (id TEXT PRIMARY KEY, ceiling TEXT, period TEXT, period_key TEXT, limit_m INTEGER,
  state TEXT NOT NULL, opened_at TEXT, answered_by TEXT, answered_at TEXT);
CREATE TABLE IF NOT EXISTS halts (cause TEXT PRIMARY KEY, by TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS readings (name TEXT, month TEXT, micros INTEGER, PRIMARY KEY (name, month));
CREATE TABLE IF NOT EXISTS once (key TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS journal (seq INTEGER PRIMARY KEY, at TEXT, kind TEXT, ref TEXT, body TEXT, prev TEXT,
  hash TEXT);
"""


def money(v) -> Decimal:
    """A non-negative finite USD amount as Decimal, rounded UP to a micro-dollar (never under-counted)."""
    if v is None or isinstance(v, bool):
        raise ValueError("an amount is a number")
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"not an amount: {v!r}") from exc
    if not d.is_finite() or d < 0:
        raise ValueError(f"an amount is finite and not negative: {v!r}")
    return d.quantize(_MICRO, rounding=ROUND_CEILING)


def _m(v) -> int:
    return int(money(v) / _MICRO)


def _usd(micros: int) -> Decimal:
    return (Decimal(micros) * _MICRO).quantize(_MICRO)


@dataclass(frozen=True)
class Ceiling:
    """A limit over one period. `match` selects the calls it counts (all of its pairs must be in the call's scopes);
    a limit of 0 switches the route off. `on_exhaust` tells the caller what to do (refuse, degrade, defer...)."""
    name: str
    period: str
    limit_usd: object
    match: Mapping[str, str] = field(default_factory=dict)
    on_exhaust: str = "refuse"


@dataclass(frozen=True)
class OtherConsumer:
    """Another spender on the same provider key. `read(month)` returns its spend this UTC month or None when it
    cannot be read; None counts its whole `cap_usd` (unreadable is never zero). It always counts in the month
    ceiling; with `scopes` it also counts in every scoped month ceiling whose `match` its scopes satisfy (a pool
    shared with an outside engine)."""
    name: str
    read: Callable[[str], object]
    cap_usd: object
    scopes: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Velocity:
    """Halt when the last `window_s` spend is at least `floor_usd` and above `factor` x the normal rate of the
    previous 24 h: a loop, not work. Only `resume("velocity")` lifts it."""
    window_s: int = 900
    floor_usd: object = "2"
    factor: object = "6"


@dataclass(frozen=True)
class Policy:
    """`key_limit_usd` is the provider key's own monthly limit (the backstop); `monthly_stop_usd` the code's stop just
    under it (default 95 % of it). `daily_usd` an optional UTC-day ceiling. `ceilings` the scoped ones."""
    key_limit_usd: object = "100"
    monthly_stop_usd: object = None
    daily_usd: object = None
    ceilings: tuple = ()
    per_call_max_usd: object = None
    on_month_exhaust: str = "refuse"
    on_day_exhaust: str = "degrade"
    others: tuple = ()
    key_usage: Optional[Callable[[str], object]] = None
    velocity: Optional[Velocity] = None

    def stop(self) -> Decimal:
        return money(self.monthly_stop_usd) if self.monthly_stop_usd is not None else money(
            money(self.key_limit_usd) * Decimal("0.95"))

    def all_ceilings(self) -> list:
        out = [Ceiling("month", "month", self.stop(), on_exhaust=self.on_month_exhaust)]
        if self.daily_usd is not None:
            out.append(Ceiling("day", "day", self.daily_usd, on_exhaust=self.on_day_exhaust))
        return out + list(self.ceilings)


def policy_problems(policy: Policy) -> list:
    """Hard errors: the constructor refuses a policy that has any."""
    out = []
    try:
        key, stop = money(policy.key_limit_usd), policy.stop()
    except ValueError as exc:
        return [str(exc)]
    if not 0 < stop < key:
        out.append("the code's monthly stop must sit above 0 and under the key's own limit")
    seen, lanes = set(), Decimal(0)
    out += [f"ceiling {c.name!r}: 'month' and 'day' are the policy's own names" for c in policy.ceilings
            if c.name in ("month", "day")]
    for c in policy.all_ceilings():
        if c.name in seen:
            out.append(f"ceiling {c.name!r}: names are unique")
        seen.add(c.name)
        if c.period not in PERIODS:
            out.append(f"ceiling {c.name}: period is one of {PERIODS}")
        try:
            limit = money(c.limit_usd)
        except ValueError:
            out.append(f"ceiling {c.name}: the limit is a number (unknown is no limit, it is an error)")
            continue
        if c.period == "month" and set(c.match) == {"lane"}:
            lanes += limit
    if lanes > stop:
        out.append(f"lanes total {lanes} exceed the monthly stop {stop}")
    for name in ("daily_usd", "per_call_max_usd"):
        v = getattr(policy, name)
        if v is not None and (_safe(v) is None or _safe(v) <= 0):
            out.append(f"{name} must be a positive amount")
    return out


def policy_warnings(policy: Policy, days: int = 31) -> list:
    """Assembly advice: a daily ceiling that, every day, would outrun the key's limit."""
    if policy.daily_usd is not None and money(policy.daily_usd) * days > money(policy.key_limit_usd):
        return [f"daily ceiling x {days} days exceeds the key's limit"]
    return []


def _safe(v):
    try:
        return money(v)
    except ValueError:
        return None


@dataclass(frozen=True)
class Ask:
    """'Ceiling X reached, double to 2X or keep?' with no recommended option. `new` is True only when it opened now."""
    id: str
    ceiling: str
    period: str
    period_key: str
    limit_usd: Decimal
    doubled_usd: Decimal
    state: str
    text: str
    new: bool = False
    options: tuple = ("double", "keep")
    recommended: None = None


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    call_id: str
    worst_case_usd: Decimal
    ceiling: Optional[str] = None
    period_key: Optional[str] = None
    limit_usd: Optional[Decimal] = None
    committed_usd: Optional[Decimal] = None
    on_exhaust: Optional[str] = None
    blocked_by: tuple = ()
    ask: Optional[Ask] = None
    degraded: tuple = ()


class SpendLedger:
    """The guard and its durable ledger. Thread-safe; several processes may share one database file."""

    def __init__(self, policy: Policy, path: str = ":memory:", clock: Optional[Callable[[], datetime]] = None,
                 notify: Optional[Callable[[dict], None]] = None, *, storage: str = "sqlite"):
        problems = policy_problems(policy)
        if problems:
            raise ValueError("; ".join(problems))
        if storage not in STORAGES:
            raise ValueError(f"storage is one of {STORAGES}")
        self.policy, self.clock, self.notify = policy, clock or (lambda: datetime.now(timezone.utc)), notify
        self.storage = storage
        self._lock = threading.RLock()
        self._outbox: list = []
        self._reader_notes: tuple = ()
        self._ops: Optional[list] = None  # the current transaction's changes, jsonl store only
        self._file: Optional[_JournalFile] = None
        if storage == "sqlite":
            self.db = sqlite3.connect(path, isolation_level=None, timeout=30, check_same_thread=False)
            self.db.executescript(SCHEMA)
            return
        if not path or str(path) == ":memory:":
            raise ValueError("the jsonl store is a file: give its path")
        if fcntl is None:  # pragma: no cover
            raise ValueError("the jsonl store needs POSIX file locks (fcntl)")
        self._file = _JournalFile(str(path))
        self.db = _mirror()
        with self._held():
            self._sync()

    # time, transactions, journal ----------------------------------------------------------------------------------
    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("a naive clock cannot say which UTC day or month it is")
        return now.astimezone(timezone.utc)

    @contextmanager
    def _tx(self):
        with self._held():
            if self._file is not None:
                self._sync()
            self.db.execute("BEGIN IMMEDIATE")
            self._ops = [] if self._file is not None else None
            appended = False
            try:
                if self._file is not None and self._file.tail:
                    t = self._file.tail
                    self._journal(self.db, "ledger.torn", "file", {"bytes": len(t),
                                                                   "sha256": hashlib.sha256(t).hexdigest()},
                                  self._now())
                yield self.db
                if self._ops:
                    self._append(self._ops)
                    appended = True
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                self._outbox.clear()
                if appended:  # on disk but not in the index: rebuild the index from the file
                    self._rebuild()
                raise
            finally:
                self._ops = None
            sent, self._outbox = self._outbox, []
        for ev in sent:
            if self.notify:
                try:
                    self.notify(ev)
                except Exception:  # noqa: BLE001 - telling never breaks the guard; the event stays in the journal
                    pass

    def _journal(self, db, kind: str, ref: str, body: dict, now: datetime, event: bool = False) -> None:
        seq, prev = db.execute("SELECT seq, hash FROM journal ORDER BY seq DESC LIMIT 1").fetchone() or (0, "0" * 64)
        text = json.dumps(body, sort_keys=True, default=str)
        h = _chain(prev, seq + 1, now.isoformat(), kind, ref, text)
        self._ins(db, "journal", {"seq": seq + 1, "at": now.isoformat(), "kind": kind, "ref": ref, "body": text,
                                  "prev": prev, "hash": h})
        if event:
            self._outbox.append({"kind": kind, "ref": ref, **body})

    def _q(self, sql: str, args=()) -> list:
        with self._lock:
            if self._file is not None and self._file.depth == 0:
                with self._held():
                    self._sync()
                    return self.db.execute(sql, args).fetchall()
            return self.db.execute(sql, args).fetchall()

    # writes: every change goes through these three, so the jsonl store can journal it --------------------------
    def _ins(self, db, table: str, row: dict, conflict: str = ""):
        cur = db.execute(_insert_sql(table, tuple(row), conflict), tuple(row.values()))
        if self._ops is not None and cur.rowcount:
            if table == "calls" and "rid" not in row:
                row = {"rid": cur.lastrowid, **row}
            self._ops.append(["i", table, conflict, dict(row)])
        return cur

    def _upd(self, db, table: str, sets: dict, where: dict) -> None:
        db.execute(_update_sql(table, tuple(sets), tuple(where)), (*sets.values(), *where.values()))
        if self._ops is not None:
            self._ops.append(["u", table, dict(sets), dict(where)])

    def _del(self, db, table: str, where: dict) -> None:
        db.execute(_delete_sql(table, tuple(where)), tuple(where.values()))
        if self._ops is not None:
            self._ops.append(["d", table, dict(where)])

    def _once(self, db, key: str) -> bool:
        return self._ins(db, "once", {"key": key}, "IGNORE").rowcount == 1

    # the jsonl store -----------------------------------------------------------------------------------------------
    @contextmanager
    def _held(self):
        """This instance's lock and, for the jsonl store, the lock file (once, however deep the nesting)."""
        with self._lock:
            f = self._file
            if f is None:
                yield
                return
            if f.depth == 0:
                fcntl.flock(f.lock_fd, fcntl.LOCK_EX)
            f.depth += 1
            try:
                yield
            finally:
                f.depth -= 1
                if f.depth == 0:
                    fcntl.flock(f.lock_fd, fcntl.LOCK_UN)

    def _sync(self) -> None:
        """Replay the lines other writers appended since the last read (the lock is held, no transaction open)."""
        f = self._file
        try:
            with open(f.path, "rb") as fh:
                if os.fstat(fh.fileno()).st_size < f.offset:  # the file was cut or rewritten under us
                    self._rebuild()
                    return
                fh.seek(f.offset)
                data = fh.read()
        except FileNotFoundError:
            data = b""
            if f.offset:
                self._rebuild()
                return
        head, sep, f.tail = data.rpartition(b"\n")
        if not sep:
            return
        for raw in head.split(b"\n"):
            self._replay(raw)
        f.offset += len(head) + 1

    def _replay(self, raw: bytes) -> None:
        f = self._file
        try:
            rec = json.loads(raw.decode("utf-8"))
            if not isinstance(rec, dict) or set(rec) != _LINE_KEYS or not isinstance(rec["ops"], list) \
                    or isinstance(rec["n"], bool) or not isinstance(rec["n"], int):
                raise ValueError("not a journal line")
        except (ValueError, UnicodeDecodeError):
            f.bad += 1
            return
        n, ops, prev, h = rec["n"], rec["ops"], rec["prev"], rec["h"]
        self.db.execute("BEGIN")
        try:
            for op in ops:
                _apply(self.db, op)
            self.db.execute("COMMIT")
        except (ValueError, TypeError, KeyError, IndexError, OverflowError, sqlite3.Error):
            self.db.execute("ROLLBACK")
            f.bad += 1
            return
        if prev != f.last or n != f.n + 1 or h != _line_hash(prev, n, ops):
            f.broken = True
        f.n, f.last = n, str(h)

    def _append(self, ops: list) -> None:
        """One line for the transaction, written whole and fsynced before the answer; a failure cuts it back."""
        f = self._file
        n, prev = f.n + 1, f.last
        h = _line_hash(prev, n, ops)
        line = (json.dumps({"n": n, "ops": ops, "prev": prev, "h": h}, sort_keys=True) + "\n").encode("utf-8")
        fd = os.open(f.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if f.tail:  # a torn line a crash left behind: never part of the chain, dropped before the next line
                os.ftruncate(fd, f.offset)
            start = os.lseek(fd, 0, os.SEEK_END)
            if start != f.offset:
                raise RuntimeError("the journal file changed without its lock")
            try:
                view = memoryview(line)
                while view:
                    view = view[os.write(fd, view):]
                os.fsync(fd)
            except BaseException:
                try:
                    os.ftruncate(fd, start)
                except OSError:
                    pass
                raise
        finally:
            os.close(fd)
        if start == 0:  # a new file: its directory entry is made durable too
            try:
                dfd = os.open(os.path.dirname(os.path.abspath(f.path)), os.O_RDONLY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
            except OSError:
                pass
        f.offset, f.n, f.last, f.tail = start + len(line), n, h, b""

    def _rebuild(self) -> None:
        self.db.close()
        self.db = _mirror()
        self._file.reset()
        self._sync()

    def _file_intact(self) -> bool:
        """Every whole line of the file parses and chains to the one before (a torn last line is not a line)."""
        with self._held():
            try:
                with open(self._file.path, "rb") as fh:
                    data = fh.read()
            except FileNotFoundError:
                data = b""
        head, sep, _ = data.rpartition(b"\n")
        prev, n = "0" * 64, 0
        for raw in head.split(b"\n") if sep else ():
            try:
                rec = json.loads(raw.decode("utf-8"))
                ok = isinstance(rec, dict) and set(rec) == _LINE_KEYS and rec["prev"] == prev and rec["n"] == n + 1 \
                    and rec["h"] == _line_hash(prev, rec["n"], rec["ops"])
            except (ValueError, UnicodeDecodeError, TypeError):
                return False
            if not ok:
                return False
            prev, n = rec["h"], rec["n"]
        return True

    def verify_journal(self) -> bool:
        """True when no journal row was edited, removed or reordered (and, for the jsonl store, no line of the file:
        every change of every table is chained there, not only the journal's rows)."""
        if self._file is not None and (not self._file_intact() or self._file.broken or self._file.bad):
            return False
        prev = "0" * 64
        for seq, at, kind, ref, body, p, h in self._q("SELECT * FROM journal ORDER BY seq"):
            if p != prev or h != _chain(prev, seq, at, kind, ref, body):
                return False
            prev = h
        return True

    # ceilings ----------------------------------------------------------------------------------------------------
    def _limit_m(self, c: Ceiling) -> int:
        row = self._q("SELECT micros FROM overrides WHERE name=?", (c.name,))
        return row[0][0] if row else _m(c.limit_usd)

    def key_limit(self) -> Decimal:
        row = self._q("SELECT micros FROM overrides WHERE name='__key_limit__'")
        return _usd(row[0][0]) if row else money(self.policy.key_limit_usd)

    def limit(self, name: str) -> Decimal:
        return _usd(self._limit_m(self._ceiling(name)))

    def _ceiling(self, name: str) -> Ceiling:
        for c in self.policy.all_ceilings():
            if c.name == name:
                return c
        raise KeyError(name)

    @staticmethod
    def _period_key(c: Ceiling, now: datetime) -> str:
        if c.period in ROLLING_S:  # a keep or an ask on a rolling ceiling holds for the UTC day it was given
            return f"{c.period}@{now.strftime('%Y-%m-%d')}"
        return {"day": now.strftime("%Y-%m-%d"), "month": now.strftime("%Y-%m"), "total": "total"}[c.period]

    def _own_m(self, c: Ceiling, now: datetime) -> int:
        if c.period in ROLLING_S:
            where = ("ts>?", (now.timestamp() - ROLLING_S[c.period],))
        else:
            where = {"day": ("day=?", (now.strftime("%Y-%m-%d"),)), "month": ("month=?", (now.strftime("%Y-%m"),)),
                     "total": ("1=1", ())}[c.period]
        if not c.match:
            return self._q(f"SELECT COALESCE(SUM(counted),0) FROM calls WHERE {where[0]}", where[1])[0][0]
        total = 0
        for scopes, counted in self._q(f"SELECT scopes, counted FROM calls WHERE {where[0]}", where[1]):
            s = json.loads(scopes)
            if all(s.get(k) == str(v) for k, v in c.match.items()):
                total += counted
        return total

    def _committed_m(self, c: Ceiling, now: datetime, outside=(0, None, ())) -> int:
        own = self._own_m(c, now)
        others, key_usage, *rest = outside
        if c.name == "month":
            return max(own + others, key_usage or 0)
        if c.period == "month" and c.match and rest:
            own += sum(m for scopes, m in rest[0] if all(scopes.get(k) == str(v) for k, v in c.match.items()))
        return own

    def committed(self, name: str) -> Decimal:
        """Settled plus open (reserved or unknown) spend this period, as the guard counts it."""
        now, c = self._now(), self._ceiling(name)
        return _usd(self._committed_m(c, now, _figures(self._outside(now.strftime("%Y-%m")))))

    def _outside(self, month: str):
        """(others' spend, the provider's own usage or None, notes, readings to keep, (scopes, spend) of each scoped
        consumer). Called outside the write lock: a reader may be slow, the transaction must not wait on it."""
        total, notes, keep, scoped = 0, [], [], []
        for o in self.policy.others:
            try:
                v = _safe(o.read(month))
            except Exception:  # noqa: BLE001 - an unreadable consumer is counted at its cap
                v = None
            row = (self._q("SELECT micros FROM readings WHERE name=? AND month=?", (o.name, month)) or [None])[0]
            if v is None:
                m = _m(o.cap_usd)
                notes.append(f"other:{o.name}:unreadable, counted at its cap")
            else:
                m = max(_m(v), row[0] if row else 0)  # spend never falls within a month
                keep.append((o.name, month, m))
            total += m
            if o.scopes:
                scoped.append(({str(k): str(x) for k, x in o.scopes.items()}, m))
        usage = None
        if self.policy.key_usage is not None:
            try:
                usage = _safe(self.policy.key_usage(month))
            except Exception:  # noqa: BLE001
                usage = None
            if usage is None:
                notes.append("key-usage:unreadable, the own ledger binds alone")
        return total, (None if usage is None else _m(usage)), tuple(notes), keep, tuple(scoped)

    # the guard ---------------------------------------------------------------------------------------------------
    def reserve(self, call_id: str, worst_case_usd, *, scopes: Optional[Mapping[str, str]] = None,
                op_key: Optional[str] = None, label: str = "") -> Decision:
        """Hold the call's worst case before it is sent. Allowed only if every applying ceiling still holds it."""
        if not call_id:
            raise ValueError("a call id is required")
        worst = _m(worst_case_usd)
        if worst <= 0:
            raise ValueError("a worst case is above zero: a zero or negative hold would make room for others")
        scopes = {str(k): str(v) for k, v in (scopes or {}).items()}
        op, now = op_key or call_id, self._now()
        day, month = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
        others, usage, notes, keep, scoped = self._outside(month)
        self._reader_notes = notes
        base = dict(call_id=call_id, worst_case_usd=_usd(worst), degraded=notes)
        with self._tx() as db:
            for name, mon, micros in keep:
                self._ins(db, "readings", {"name": name, "month": mon, "micros": micros}, "REPLACE")
            rows = db.execute("SELECT call_id, state FROM calls WHERE (call_id=? OR op_key=?) AND state!='released'",
                              (call_id, op)).fetchall()
            if any(s == "unknown" for _, s in rows):
                return Decision(False, "unknown_outcome", **base)
            for cid, state in rows:
                if cid == call_id:
                    return Decision(state == "reserved", "already_reserved" if state == "reserved"
                                    else "already_settled", **base)
                if state == "reserved":
                    return Decision(False, "operation_open", **base)
            halts = [h for (h,) in db.execute("SELECT cause FROM halts ORDER BY cause")]
            if halts:
                return Decision(False, "halted", blocked_by=tuple(halts), **base)
            if self.policy.per_call_max_usd is not None and worst > _m(self.policy.per_call_max_usd):
                return Decision(False, "per_call", limit_usd=money(self.policy.per_call_max_usd), **base)
            if self._velocity_hit(db, now, worst):
                return Decision(False, "velocity", blocked_by=("velocity",), **base)
            failing = []
            for c in self.policy.all_ceilings():
                if all(scopes.get(k) == str(v) for k, v in c.match.items()):
                    limit, have = self._limit_m(c), self._committed_m(c, now, (others, usage, scoped))
                    if have + worst > limit:
                        failing.append((c, limit, have))
            if failing:
                c, limit, have = failing[0]
                pk = self._period_key(c, now)
                if self._once(db, f"reached|{c.name}|{pk}|{limit}"):
                    self._journal(db, "budget.reached", c.name, {"period": pk, "limit_usd": _usd(limit)}, now, True)
                ask = self._ask(db, c, limit, pk, now) if limit > 0 else None
                return Decision(False, "ceiling", ceiling=c.name, period_key=pk, limit_usd=_usd(limit),
                                committed_usd=_usd(have), on_exhaust=c.on_exhaust, ask=ask,
                                blocked_by=tuple(f[0].name for f in failing), **base)
            self._ins(db, "calls", {"call_id": call_id, "op_key": op, "label": label,
                                    "scopes": json.dumps(scopes, sort_keys=True), "day": day, "month": month,
                                    "ts": now.timestamp(), "worst": worst, "counted": worst, "state": "reserved"})
            self._journal(db, "reserve", call_id, {"op": op, "worst_m": worst, "scopes": scopes, "label": label}, now)
            self._warn(db, scopes, now, (others, usage, scoped))
        return Decision(True, "reserved", **base)

    def _velocity_hit(self, db, now: datetime, worst: int) -> bool:
        v = self.policy.velocity
        if v is None:
            return False
        t = now.timestamp()
        win = db.execute("SELECT COALESCE(SUM(counted),0) FROM calls WHERE ts>?", (t - v.window_s,)).fetchone()[0]
        base = db.execute("SELECT COALESCE(SUM(counted),0) FROM calls WHERE ts>? AND ts<=?",
                          (t - 86400, t - v.window_s)).fetchone()[0]
        normal = Decimal(base) / (Decimal(86400 - v.window_s) / v.window_s)
        spend = win + worst
        if spend >= _m(v.floor_usd) and normal > 0 and spend > money(v.factor) * normal:
            self._ins(db, "halts", {"cause": "velocity", "by": "guard", "at": now.isoformat()}, "IGNORE")
            self._journal(db, "budget.halt", "velocity", {"window_usd": _usd(spend), "normal_usd": _usd(int(normal))},
                          now, True)
            return True
        return False

    def _warn(self, db, scopes: dict, now: datetime, outside) -> None:
        for c in self.policy.all_ceilings():
            if c.match and not all(scopes.get(k) == str(v) for k, v in c.match.items()):
                continue
            limit, have = self._limit_m(c), self._committed_m(c, now, outside)
            pk = self._period_key(c, now)
            if limit and have >= WARN_SHARE * limit and self._once(db, f"warn|{c.name}|{pk}|{limit}"):
                self._journal(db, "budget.warn", c.name, {"period": pk, "committed_usd": _usd(have),
                                                          "limit_usd": _usd(limit)}, now, True)
            if have > limit and self._once(db, f"breach|{c.name}|{pk}|{limit}"):
                self._journal(db, "budget.breach", c.name, {"period": pk, "committed_usd": _usd(have),
                                                            "limit_usd": _usd(limit)}, now, True)

    def _ask(self, db, c: Ceiling, limit: int, pk: str, now: datetime) -> Ask:
        aid = "ask-" + hashlib.sha256(f"{c.name}|{limit}|{pk}".encode()).hexdigest()[:12]
        row = db.execute("SELECT state FROM asks WHERE id=?", (aid,)).fetchone()
        new = row is None
        if new:
            self._ins(db, "asks", {"id": aid, "ceiling": c.name, "period": c.period, "period_key": pk,
                                   "limit_m": limit, "state": "open", "opened_at": now.isoformat()})
        ask = self._ask_view(aid, c.name, c.period, pk, limit, "open" if new else row[0], new)
        if new:
            self._journal(db, "budget.ask", aid, {"ceiling": c.name, "period": pk, "text": ask.text}, now, True)
        return ask

    @staticmethod
    def _ask_view(aid, name, period, pk, limit, state, new=False) -> Ask:
        text = (f"The {name} ceiling of {_usd(limit)} USD ({period} {pk}) is reached. "
                f"Double it to {_usd(2 * limit)} USD, or keep it?")
        return Ask(aid, name, period, pk, _usd(limit), _usd(2 * limit), state, text, new)

    def open_asks(self) -> list:
        return [self._ask_view(*r) for r in self._q(
            "SELECT id, ceiling, period, period_key, limit_m, state FROM asks WHERE state='open' ORDER BY opened_at")]

    def answer(self, ask_id: str, choice: str, *, operator: bool, by: str) -> Decimal:
        """'double' only from the operator's own session; 'keep' from anyone. Returns the limit in force after."""
        if choice not in ("double", "keep"):
            raise ValueError("answer double or keep")
        if choice == "double" and not operator:
            raise PermissionError("operator_session_required")
        now = self._now()
        with self._tx() as db:
            row = db.execute("SELECT ceiling, limit_m, state FROM asks WHERE id=?", (ask_id,)).fetchone()
            if not row or row[2] != "open":
                raise ValueError("there is no open ask with this id")
            name, asked, _ = row
            c = self._ceiling(name)
            current = self._limit_m(c)
            new = max(current, 2 * asked) if choice == "double" else current  # never doubled twice
            self._upd(db, "asks", {"state": choice, "answered_by": by, "answered_at": now.isoformat()},
                      {"id": ask_id})
            self._journal(db, "budget.answer", ask_id, {"ceiling": name, "answer": choice, "by": by}, now)
            if new != current:
                self._ins(db, "overrides", {"name": name, "micros": new}, "REPLACE")
                self._journal(db, "budget.ceiling_raised", name, {"from_usd": _usd(current), "to_usd": _usd(new),
                                                                  "by": by}, now, True)
                if name == "month":  # the stop stays under the key's own limit: the key must be raised as well
                    old_key = _m(self.key_limit())
                    new_key = max(old_key, new + (old_key - current))
                    self._ins(db, "overrides", {"name": "__key_limit__", "micros": new_key}, "REPLACE")
                    self._journal(db, "budget.key_limit_raise", "key", {"from_usd": _usd(old_key),
                                                                         "to_usd": _usd(new_key)}, now, True)
        return _usd(new)

    # after the call ----------------------------------------------------------------------------------------------
    def _row(self, db, call_id: str):
        row = db.execute("SELECT rid, state, worst, counted, label, scopes FROM calls WHERE call_id=? "
                         "ORDER BY rid DESC LIMIT 1", (call_id,)).fetchone()
        if row is None:
            raise KeyError(f"no reservation for {call_id}")
        return row

    def settle(self, call_id: str, cost_usd, *, confirmed: bool = True) -> Decimal:
        """The call ran. A confirmed provider cost is recorded as is (a confirmed 0 is a real 0, a cost above the worst
        case is counted in full); no cost or an unconfirmed one keeps the worst case. A repeat keeps the first
        figure."""
        now = self._now()
        outside = _figures(self._outside(now.strftime("%Y-%m")))
        with self._tx() as db:
            rid, state, worst, counted, label, scopes = self._row(db, call_id)
            if state == "settled":
                return _usd(counted)
            if state != "reserved":
                raise ValueError(f"{call_id} is {state}: an unknown outcome is reconciled with evidence")
            cost = None if cost_usd is None else _m(cost_usd)
            known = cost is not None and confirmed
            counted = cost if known else worst
            self._upd(db, "calls", {"state": "settled", "cost": cost, "confirmed": int(known), "counted": counted},
                      {"rid": rid})
            self._journal(db, "settle", call_id, {"cost_m": cost, "confirmed": known, "counted_m": counted}, now)
            if known and cost > DRIFT_RATIO * worst and self._once(db, f"drift|{label}|{now:%Y-%m-%d}"):
                self._journal(db, "budget.drift", label or call_id, {"worst_usd": _usd(worst), "cost_usd": _usd(cost)},
                              now, True)
            self._warn(db, json.loads(scopes), now, outside)
        return _usd(counted)

    def report_spend(self, call_id: str, cost_usd, *, scopes: Optional[Mapping[str, str]] = None, label: str = "",
                     evidence: str) -> Decimal:
        """Spend that happened outside a reservation (an invoice line, a charge another process made for this
        ledger's scopes): recorded settled and confirmed at its cost and counted in every ceiling its scopes match.
        Money already spent is never refused; it warns and breaches like any spend. Once per call id: a repeat with
        the same cost and scopes answers the first figure, anything else is refused."""
        if not call_id:
            raise ValueError("a call id is required")
        if not str(evidence or "").strip():
            raise ValueError("spend reported outside a reservation needs its evidence")
        cost = _m(cost_usd)
        if cost <= 0:
            raise ValueError("a reported spend is above zero")
        scopes = {str(k): str(v) for k, v in (scopes or {}).items()}
        now = self._now()
        outside = _figures(self._outside(now.strftime("%Y-%m")))
        with self._tx() as db:
            old = db.execute("SELECT state, counted, scopes, worst, cost FROM calls WHERE call_id=? ORDER BY rid DESC "
                             "LIMIT 1", (call_id,)).fetchone()
            if old is not None:
                state, counted, old_scopes, worst, old_cost = old
                if state == "settled" and old_cost == cost and worst == cost and json.loads(old_scopes) == scopes:
                    return _usd(counted)
                raise ValueError(f"{call_id} is already recorded ({state}); a reserved call is settled, not reported")
            self._ins(db, "calls", {"call_id": call_id, "op_key": call_id, "label": label,
                                    "scopes": json.dumps(scopes, sort_keys=True), "day": now.strftime("%Y-%m-%d"),
                                    "month": now.strftime("%Y-%m"), "ts": now.timestamp(), "worst": cost,
                                    "cost": cost, "confirmed": 1, "counted": cost, "state": "settled",
                                    "note": str(evidence)[:300]})
            self._journal(db, "report", call_id, {"cost_m": cost, "scopes": scopes, "label": label,
                                                  "evidence": str(evidence)[:300]}, now)
            self._warn(db, scopes, now, outside)
        return _usd(cost)

    def release(self, call_id: str, evidence: str) -> None:
        """The call provably never left (refused before sending, failed before dispatch): its hold is freed."""
        self._close(call_id, "released", 0, evidence, ("reserved",))

    def mark_unknown(self, call_id: str, note: str = "") -> None:
        """Nobody knows whether it charged (a timeout after sending, a crash): it counts in full and blocks a retry."""
        self._close(call_id, "unknown", None, note, ("reserved",))

    def reconcile(self, call_id: str, cost_usd, evidence: str) -> Decimal:
        """Close an unknown outcome with evidence (a provider receipt or usage line); cost 0 releases it."""
        if not str(evidence or "").strip():
            raise ValueError("an unknown outcome is reconciled only with evidence")
        cost = _m(cost_usd)
        self._close(call_id, "settled" if cost else "released", cost, evidence, ("unknown",))
        return _usd(cost)

    def _close(self, call_id: str, state: str, counted: Optional[int], note: str, allowed: tuple) -> None:
        if state == "released" and not str(note or "").strip():
            raise ValueError("a release needs its evidence: the call provably never left")
        now = self._now()
        outside = _figures(self._outside(now.strftime("%Y-%m"))) if state == "settled" else (0, None, ())
        with self._tx() as db:
            rid, cur, worst, _, _, scopes = self._row(db, call_id)
            if cur not in allowed:
                raise ValueError(f"{call_id} is {cur}, not {' or '.join(allowed)}")
            c = worst if counted is None else counted
            confirmed = int(state == "settled")
            self._upd(db, "calls", {"state": state, "counted": c, "cost": None if state == "unknown" else c,
                                    "confirmed": confirmed, "note": note}, {"rid": rid})
            self._journal(db, state, call_id, {"counted_m": c, "note": note}, now)
            if state == "settled":
                self._warn(db, json.loads(scopes), now, outside)

    def expire_open(self, max_age: timedelta) -> list:
        """Reservations older than `max_age` (a crash left them) become unknown: they keep counting, need reconcile."""
        now = self._now()
        cutoff = (now - max_age).timestamp()
        ids = [r[0] for r in self._q("SELECT call_id FROM calls WHERE state='reserved' AND ts<?", (cutoff,))]
        for cid in ids:
            self.mark_unknown(cid, "expired without a settlement")
        return ids

    # stops, reading ----------------------------------------------------------------------------------------------
    def halt(self, cause: str, by: str) -> None:
        """A hard stop (emergency, operator, deletion pending...): every reserve is refused until `resume`."""
        now = self._now()
        with self._tx() as db:
            self._ins(db, "halts", {"cause": cause, "by": by, "at": now.isoformat()}, "REPLACE")
            self._journal(db, "budget.halt", cause, {"by": by}, now, True)

    def resume(self, cause: str, by: str) -> None:
        """Lift one cause; the others stay."""
        now = self._now()
        with self._tx() as db:
            self._del(db, "halts", {"cause": cause})
            self._journal(db, "budget.resume", cause, {"by": by}, now, True)

    def halted(self) -> list:
        return [h for (h,) in self._q("SELECT cause FROM halts ORDER BY cause")]

    def under_pace(self, reserve_usd=0) -> bool:
        """Room for background work: the month's committed spend is at or under the stop's share of the month gone,
        less a reserve kept for live work."""
        now = self._now()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start + timedelta(days=32)).replace(day=1)
        share = Decimal(str((now - start) / (end - start)))
        line = max(Decimal(0), (self.limit("month") - money(reserve_usd)) * share)
        return self.committed("month") <= line

    def usage(self, month: Optional[str] = None) -> dict:
        """The month's usage report: confirmed cost, what the guard counts, calls without a confirmed cost."""
        month = month or self._now().strftime("%Y-%m")
        rows = self._q("SELECT state, confirmed, cost, counted FROM calls WHERE month=?", (month,))
        return {"month": month, "calls": len(rows),
                "confirmed_usd": _usd(sum(r[2] or 0 for r in rows if r[1])),
                "counted_usd": _usd(sum(r[3] for r in rows)),
                "unpriced_calls": sum(1 for r in rows if r[0] == "settled" and not r[1]),
                "unknown_calls": sum(1 for r in rows if r[0] == "unknown"),
                "open_calls": sum(1 for r in rows if r[0] == "reserved")}

    def status(self) -> dict:
        now, out = self._now(), []
        outside = self._outside(now.strftime("%Y-%m"))
        for c in self.policy.all_ceilings():
            limit, have = self._limit_m(c), self._committed_m(c, now, _figures(outside))
            state = "exhausted" if have >= limit else "warn" if have >= WARN_SHARE * limit else "ok"
            out.append({"name": c.name, "period": c.period, "period_key": self._period_key(c, now),
                        "limit_usd": _usd(limit), "committed_usd": _usd(have),
                        "remaining_usd": _usd(max(0, limit - have)), "state": state, "on_exhaust": c.on_exhaust})
        return {"ceilings": out, "key_limit_usd": self.key_limit(), "halted": self.halted(),
                "open_asks": [a.id for a in self.open_asks()], "degraded": self.degraded()}

    def degraded(self) -> list:
        """Entries for a service's `degraded` list (fabric-service/0.1): empty means healthy."""
        now, out = self._now(), []
        for h in self.halted():
            out.append({"source": "budget", "reason": f"spending halted: {h}"})
        outside = self._outside(now.strftime("%Y-%m"))
        for c in self.policy.all_ceilings():
            if c.name not in ("month", "day"):
                continue
            if self._committed_m(c, now, _figures(outside)) >= self._limit_m(c):
                out.append({"source": "budget", "reason": f"the {c.name} ceiling is reached: {c.on_exhaust}"})
        u = self.usage()
        if u["unpriced_calls"] or u["unknown_calls"]:
            out.append({"source": "usage", "reason": f"{u['unpriced_calls']} call(s) without a confirmed cost and "
                                                     f"{u['unknown_calls']} unknown outcome(s) counted at worst case"})
        out.extend({"source": "budget", "reason": n} for n in outside[2])
        if self._file is not None:
            with self._held():
                self._sync()
                tail, bad, broken = len(self._file.tail), self._file.bad, self._file.broken
            if tail:
                out.append({"source": "ledger", "reason": f"a torn last line of the journal file ({tail} bytes) is "
                                                          "ignored: a write was cut short; the next write drops it"})
            if bad:
                out.append({"source": "ledger", "reason": f"{bad} unreadable line(s) of the journal file are skipped"})
            elif broken:
                out.append({"source": "ledger", "reason": "the journal file's chain is broken: a line was edited"})
        return out

    def events(self, kind: Optional[str] = None) -> list:
        rows = self._q("SELECT seq, at, kind, ref, body FROM journal ORDER BY seq")
        return [{"seq": s, "at": a, "kind": k, "ref": r, **json.loads(b)} for s, a, k, r, b in rows
                if (kind is None and k.startswith("budget.")) or k == kind]

    def close(self) -> None:
        self.db.close()
        if self._file is not None:
            os.close(self._file.lock_fd)


def _figures(outside: tuple) -> tuple:
    """(others' spend, the provider's usage, scoped consumers) out of `_outside`'s answer."""
    return outside[0], outside[1], outside[4]


def _chain(prev: str, seq: int, at: str, kind: str, ref: str, body: str) -> str:
    return hashlib.sha256(json.dumps([prev, seq, at, kind, ref, body], separators=(",", ":")).encode()).hexdigest()


def _line_hash(prev: str, n: int, ops: list) -> str:
    return hashlib.sha256(json.dumps([prev, n, ops], sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class _JournalFile:
    """Where the jsonl store stands in its file: bytes replayed, the last line's number and hash, a torn tail."""

    def __init__(self, path: str):
        self.path = path
        self.lock_fd = os.open(path + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        self.depth = 0
        self.reset()

    def reset(self) -> None:
        self.offset, self.n, self.last, self.tail, self.bad, self.broken = 0, 0, "0" * 64, b"", 0, False


def _mirror():
    db = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    db.executescript(SCHEMA)
    return db


def _ident(table: str, cols) -> str:
    known = _COLUMNS[table]
    for c in cols:
        if c not in known:
            raise KeyError(f"{table}.{c}")
    return table


def _insert_sql(table: str, cols: tuple, conflict: str) -> str:
    if conflict not in ("", "REPLACE", "IGNORE"):
        raise ValueError(conflict)
    verb = f"INSERT OR {conflict}" if conflict else "INSERT"
    return (f"{verb} INTO {_ident(table, cols)} ({', '.join(chr(34) + c + chr(34) for c in cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})")


def _update_sql(table: str, sets: tuple, where: tuple) -> str:
    if not sets or not where:
        raise ValueError("an update names what it sets and where")
    return (f"UPDATE {_ident(table, sets + where)} SET {', '.join(chr(34) + c + chr(34) + '=?' for c in sets)} "
            f"WHERE {' AND '.join(chr(34) + c + chr(34) + '=?' for c in where)}")


def _delete_sql(table: str, where: tuple) -> str:
    if not where:
        raise ValueError("a delete names where")
    return f"DELETE FROM {_ident(table, where)} WHERE {' AND '.join(chr(34) + c + chr(34) + '=?' for c in where)}"


def _values(row: dict) -> tuple:
    for v in row.values():
        if isinstance(v, bool) or not (v is None or isinstance(v, (str, int, float))):
            raise TypeError("a journal value is a string, a number or null")
    return tuple(row.values())


def _apply(db, op) -> None:
    """One change of a journal line, replayed into the index; tables and columns are checked against the schema."""
    if not isinstance(op, list) or not op:
        raise ValueError("not a change")
    if op[0] == "i" and len(op) == 4 and isinstance(op[3], dict):
        db.execute(_insert_sql(op[1], tuple(op[3]), op[2]), _values(op[3]))
    elif op[0] == "u" and len(op) == 4 and isinstance(op[2], dict) and isinstance(op[3], dict):
        db.execute(_update_sql(op[1], tuple(op[2]), tuple(op[3])), _values(op[2]) + _values(op[3]))
    elif op[0] == "d" and len(op) == 3 and isinstance(op[2], dict):
        db.execute(_delete_sql(op[1], tuple(op[2])), _values(op[2]))
    else:
        raise ValueError("not a change")
