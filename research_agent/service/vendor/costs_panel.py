"""The Costs section of a spending agent (pattern costs-panel 1.0.0, the operator's rule R33 O16, decision D-74).

Every agent that spends (models, media, research, cloud) shows on its dashboard what it spent by day, week and month
with charts, the limits it holds for a UTC day, an ISO week, a calendar month and an order, and the emergency stop
(USD 500 a UTC day, USD 1000 a calendar month, enforced unless lifted with the operator's decision). The agent checks
the limits itself before a paid call (`check`); a person changes one from the dashboard and an agent by the same
action (`LimitBook.set`, the capability `spend.limits.set`, dashboard parity), without code or a release, and every
change is an audit record. The shapes follow the contract's DEC-0183 (fabric-agent-contract at aeecb12a, amending the
usage report of DEC-0021 and its limits of DEC-0027): limit ids of `budgets[]`, `period: "week"`, `editable`,
`limitChanges[]`, `emergency.day` and `emergency.month`, `months[]`. A change that only tightens (a lower or a first
amount, enforced turned on) is the caller's own act; one that raises, clears or turns a limit off needs the operator's
decision, which travels beside the call (the MCP `_meta.decision`, DEC-0121 AP-2), never as an input member.

It sits beside `patterns/spend-ledger` (which reserves each call's worst case and holds the key's ceilings) and
`patterns/spend-line` (the approval line per order of media agents): the agent passes the ledger's committed spend per
window to `check`, or its rows to `spent`. Standard library only.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path

__version__ = "1.0.0"
VERSION = __version__
CONTRACT_PIN = "aeecb12a"             # fabric-agent-contract, DEC-0183
SCHEMA = "costs-panel/1"
CHANGE_SCHEMA = "costs-limit-change/1"
WINDOWS = ("day", "week", "month")    # calendar UTC: the day, the ISO week from Monday, the month
EDIT_ACTION = "spend.limits.set"      # the one write: the dashboard's control and the agent's capability (R33 O8)
READ_ACTION = "costs.panel"           # the one read: the section's data, the same for a person and an agent
LIMIT_IDS = ("costs.order", "costs.day", "costs.week", "costs.month", "emergency.day", "emergency.month")
EMERGENCY_DAY_USD = Decimal("500")
EMERGENCY_MONTH_USD = Decimal("1000")
DEFAULTS = {"costs.order": (None, True), "costs.day": (None, True), "costs.week": (None, True),
            "costs.month": (None, True), "emergency.day": (EMERGENCY_DAY_USD, True),
            "emergency.month": (EMERGENCY_MONTH_USD, True)}
VIAS = ("dashboard", "agent", "config")
SERIES_LENGTH = {"day": 31, "week": 12, "month": 12}
MAX_CHANGES = 64
UTC = dt.timezone.utc


class Refused(Exception):
    """A typed refusal of a change (DEC-0183 SL-2): `code` is unknown-limit, limit-not-editable, invalid-amount,
    operator-decision-required, decision-invalid, or invalid-input for a call that names no change."""

    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _utc(t):
    if isinstance(t, str):
        t = dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
    if not isinstance(t, dt.datetime) or t.tzinfo is None:
        raise ValueError("a time needs its offset; a naive time is never guessed")
    return t.astimezone(UTC)


def _iso(t):
    return _utc(t).strftime("%Y-%m-%dT%H:%M:%SZ")


def window_start(t, window):
    """The UTC start of the calendar window that holds `t`."""
    t = _utc(t)
    day = dt.datetime(t.year, t.month, t.day, tzinfo=UTC)
    if window == "day":
        return day
    if window == "week":
        return day - dt.timedelta(days=t.weekday())
    if window == "month":
        return dt.datetime(t.year, t.month, 1, tzinfo=UTC)
    raise ValueError(f"unknown window {window!r}; one of {WINDOWS}")


def window_key(t, window):
    """`2026-11-18`, `2026-W47` (ISO week) or `2026-11`."""
    start = window_start(t, window)
    if window == "day":
        return start.strftime("%Y-%m-%d")
    if window == "week":
        year, week, _ = start.isocalendar()
        return f"{year}-W{week:02d}"
    return start.strftime("%Y-%m")


def _step_back(start, window):
    if window == "day":
        return start - dt.timedelta(days=1)
    if window == "week":
        return start - dt.timedelta(days=7)
    return dt.datetime(start.year - (start.month == 1), 12 if start.month == 1 else start.month - 1, 1, tzinfo=UTC)


def money(v):
    """A finite, non-negative USD amount as a Decimal rounded up to a micro-dollar; refuses None, bool, NaN and
    negatives with ValueError."""
    if v is None or isinstance(v, bool):
        raise ValueError("no amount")
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise ValueError(f"not an amount: {v!r}") from None
    if not d.is_finite() or d < 0:
        raise ValueError(f"not a finite non-negative amount: {v!r}")
    return d.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)


def _plain(d):
    """`100`, `25.5`: a Decimal in plain notation without trailing zeros (never `1E+2`)."""
    t = format(d, "f")
    return t.rstrip("0").rstrip(".") if "." in t else t


def _row_cost(r):
    """(at, counted cost, unpriced, confirmed cost or None, subscription) for one row: the counted cost is the
    confirmed `usd`, else its worst case in full (an unknown cost is never zero), else zero flagged unpriced; a
    `subscription` row is an estimate, never money (contract DEC-0110). None for a row that cannot be read."""
    if not isinstance(r, dict) or "at" not in r:
        return None
    try:
        at = _utc(r["at"])
    except (ValueError, TypeError):
        return None
    sub = bool(r.get("subscription"))
    if r.get("usd") is not None:
        try:
            usd = money(r["usd"])
        except ValueError:
            return None
        return at, usd, False, usd, sub
    try:
        worst = money(r["worst_usd"]) if r.get("worst_usd") is not None else Decimal("0")
    except ValueError:
        return None
    return at, worst, True, None, sub


def spent(rows, now):
    """What the day, the week and the month that hold `now` count: {day, week, month: Decimal, unpriced, skipped}.
    A row is `{"at", "usd"}` (None when the provider gave no cost, then its `worst_usd` counts in full); a row marked
    `subscription` is an estimate and counts in no window; a torn row, a negative cost or a row after `now` is skipped
    and counted in `skipped`, never read as zero."""
    now = _utc(now)
    starts = {w: window_start(now, w) for w in WINDOWS}
    out = {w: Decimal("0") for w in WINDOWS}
    out.update(unpriced=0, skipped=0)
    for r in rows:
        c = _row_cost(r)
        if c is None or c[0] > now:
            out["skipped"] += 1
            continue
        at, usd, unpriced, _, sub = c
        if sub:
            continue  # a subscription's estimate is not money and counts in no limit (DEC-0110)
        out["unpriced"] += unpriced
        for w in WINDOWS:
            if at >= starts[w]:
                out[w] += usd
    return out


def check(spent_by_window, amount_usd, limits):
    """May a paid call of `amount_usd` (its worst case) go now? `limits` is `LimitBook.current()`. The emergency stop
    first (day, then month), then the order's limit, then the day, the week and the month: an enforced limit refuses
    when spent plus the amount would pass it; at the line it passes. Answers {allowed, reason, window, limit_usd,
    spent_usd, amount_usd}; reason `ok`, `emergency_day`, `emergency_month`, `order`, `day`, `week`, `month` or
    `invalid_amount`."""
    try:
        amount = money(amount_usd)
    except ValueError:
        return {"allowed": False, "reason": "invalid_amount", "window": None, "limit_usd": None, "spent_usd": None,
                "amount_usd": None}
    s = {w: money(spent_by_window.get(w) or 0) for w in WINDOWS}
    steps = (("emergency_day", "emergency.day", "day"), ("emergency_month", "emergency.month", "month"),
             ("order", "costs.order", None), ("day", "costs.day", "day"), ("week", "costs.week", "week"),
             ("month", "costs.month", "month"))
    for reason, lid, w in steps:
        st = limits[lid]
        line = st["limitUsd"]
        if line is None or not st["enforced"]:
            continue
        if w is None:
            if amount > line:
                return {"allowed": False, "reason": reason, "window": None, "limit_usd": line, "spent_usd": None,
                        "amount_usd": amount}
        elif s[w] + amount > line:
            return {"allowed": False, "reason": reason, "window": w, "limit_usd": line, "spent_usd": s[w],
                    "amount_usd": amount}
    return {"allowed": True, "reason": "ok", "window": None, "limit_usd": None, "spent_usd": None,
            "amount_usd": amount}


_UNSET = object()


def _decision_ok(decision):
    return (isinstance(decision, dict) and decision.get("by") == "operator"
            and isinstance(decision.get("instruction"), str) and decision["instruction"].strip())


def _state_json(st):
    return {"limitUsd": None if st[0] is None else float(st[0]), "enforced": st[1]}


class LimitBook:
    """The limits in force and every change to them: one JSON line per change, appended, never rewritten (R28). The
    limits are the fold of the changes over `DEFAULTS` (no window limit set, the emergency stop enforced at 500 a day
    and 1000 a month). A torn or foreign line is skipped."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def history(self):
        """Every change, oldest first, as written (`costs-limit-change/1`)."""
        out = []
        if not self.path.is_file():
            return out
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if (isinstance(rec, dict) and rec.get("schema") == CHANGE_SCHEMA and rec.get("limitId") in DEFAULTS
                    and isinstance(rec.get("after"), dict)):
                out.append(rec)
        return out

    def _states(self):
        st = dict(DEFAULTS)
        for rec in self.history():
            a = rec["after"]
            st[rec["limitId"]] = (None if a.get("limitUsd") is None else Decimal(str(a["limitUsd"])),
                                  bool(a.get("enforced")))
        return st

    def current(self):
        """{limit id: {limitUsd: Decimal or None, enforced: bool}} for every id of `LIMIT_IDS`."""
        return {k: {"limitUsd": v[0], "enforced": v[1]} for k, v in self._states().items()}

    def set(self, limit_id, *, limit_usd=_UNSET, enforced=None, reason, idempotency_key, via, decision=None,
            by_ref=None, at=None):
        """The one edit (`spend.limits.set`, DEC-0183 SL-2): change one limit's amount (a positive amount, or None to
        clear it) or its `enforced`, or both. Tightening (a first or lower amount, enforced turned on) is the
        caller's own act; raising, clearing or turning off needs `decision`, the operator's words relayed beside the
        call ({by: operator, instruction, at}). Answers {change, repeated}: `change` the `limitChanges[]` entry, or
        None when nothing changes (nothing written); a repeated `idempotency_key` answers its first change with
        repeated true and writes nothing. Raises `Refused`."""
        if limit_id not in DEFAULTS:
            raise Refused("unknown-limit", f"{limit_id!r} is not a limit; one of {LIMIT_IDS}")
        if via not in VIAS:
            raise Refused("invalid-input", f"via is one of {VIAS}")
        if not isinstance(reason, str) or not reason.strip() or not isinstance(idempotency_key, str) \
                or not idempotency_key.strip():
            raise Refused("invalid-input", "reason and idempotencyKey are required")
        if limit_usd is _UNSET and enforced is None:
            raise Refused("invalid-input", "name a new limitUsd, a new enforced, or both")
        new_amount = _UNSET
        if limit_usd is not _UNSET:
            if limit_usd is None:
                new_amount = None
            else:
                try:
                    new_amount = money(limit_usd)
                except ValueError:
                    raise Refused("invalid-amount", f"{limit_id} takes a positive amount or null") from None
                if new_amount <= 0:
                    raise Refused("invalid-amount", f"{limit_id} takes a positive amount or null")
        if enforced is not None and not isinstance(enforced, bool):
            raise Refused("invalid-amount", "enforced is true or false")
        if decision is not None and not _decision_ok(decision):
            raise Refused("decision-invalid", "a decision is the operator's words: {by: operator, instruction, at}")
        with self._lock:
            hist = self.history()
            for rec in hist:
                if rec.get("idempotencyKey") == idempotency_key:
                    return {"change": _public(rec), "repeated": True}
            old = self._states()[limit_id]
            amount = old[0] if new_amount is _UNSET else new_amount
            on = old[1] if enforced is None else enforced
            if (amount, on) == old:
                return {"change": None, "repeated": False}
            loosens = (on is False and old[1] is True) or (old[0] is not None and (amount is None or amount > old[0]))
            if loosens and decision is None:
                raise Refused("operator-decision-required",
                              "raising, clearing or turning off a limit needs the operator's decision")
            by = "operator" if (decision is not None or via == "dashboard") else ("service" if via == "config"
                                                                                  else "agent")
            rec = {"schema": CHANGE_SCHEMA, "id": f"chg-{len(hist) + 1:06d}", "at": _iso(at or dt.datetime.now(UTC)),
                   "by": by, "via": via, "limitId": limit_id,
                   "before": None if old == DEFAULTS[limit_id] and DEFAULTS[limit_id][0] is None else _state_json(old),
                   "after": _state_json((amount, on)), "reason": reason.strip(), "idempotencyKey": idempotency_key}
            if by_ref:
                rec["byRef"] = str(by_ref)[:128]
            if decision is not None:
                rec["decision"] = decision
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
            return {"change": _public(rec), "repeated": False}


def _public(rec):
    """A change as the usage report's `limitChanges[]` entry (DEC-0183 SL-4): no decision text, no key."""
    out = {k: rec[k] for k in ("id", "at", "by", "via", "limitId", "before", "after", "reason")}
    if rec.get("byRef"):
        out["byRef"] = rec["byRef"]
    return out


def limit_changes(book, n=MAX_CHANGES):
    """The usage report's `limitChanges[]`: newest first, at most 64."""
    return [_public(r) for r in book.history()[-n:][::-1]]


def series(rows, now, window, n=None):
    """Chart data: the last `n` buckets of `window` up to the one holding `now`, oldest first, every bucket present:
    [{key, start, usd, unpriced, state, estimate_usd}]. `usd` sums the confirmed costs, the way the usage report's
    totals do (contract DEC-0021, the fabric-dashboards daily series FD-324): `state` is `none` (no call, usd 0.0),
    `known`, `lower_bound` (some calls without a price) or `unknown` (every call without a price, usd None); a
    subscription's estimate is kept apart in `estimate_usd`, never money."""
    now = _utc(now)
    n = n or SERIES_LENGTH[window]
    starts = [window_start(now, window)]
    while len(starts) < n:
        starts.append(_step_back(starts[-1], window))
    starts.reverse()
    buckets = {window_key(s, window): {"key": window_key(s, window), "start": _iso(s), "usd": Decimal("0"),
                                       "priced": 0, "unpriced": 0, "estimate_usd": Decimal("0")} for s in starts}
    first = starts[0]
    for r in rows:
        c = _row_cost(r)
        if c is None or c[0] > now or c[0] < first:
            continue
        b = buckets.get(window_key(c[0], window))
        if b is None:
            continue
        _, _, unpriced, confirmed, sub = c
        if sub:
            b["estimate_usd"] += confirmed or Decimal("0")
        elif unpriced:
            b["unpriced"] += 1
        else:
            b["usd"] += confirmed
            b["priced"] += 1
    out = []
    for b in buckets.values():
        state = ("none" if not b["priced"] and not b["unpriced"] else "known" if not b["unpriced"]
                 else "lower_bound" if b["priced"] else "unknown")
        out.append({"key": b["key"], "start": b["start"], "usd": None if state == "unknown" else float(b["usd"]),
                    "unpriced": b["unpriced"], "priced": b["priced"], "state": state,
                    "estimate_usd": float(b["estimate_usd"])})
    return out


def months(rows, now):
    """The usage report's `months[]` (DEC-0183 SL-6): the last 12 UTC months, oldest first, the current one last:
    {month, calls, unpricedCalls, costUsd}, costUsd null when the month had calls and none was priced."""
    return [{"month": p["key"], "calls": p["priced"] + p["unpriced"], "unpricedCalls": p["unpriced"],
             "costUsd": p["usd"]} for p in series(rows, now, "month", 12)]


def _f(v):
    return None if v is None else float(v)


def panel(rows, book, now, history=20):
    """The section's data (`READ_ACTION`, schema `costs-panel/1`): per window its key, spent, limit (when set and
    enforced), what is left and whether it is tripped; the order's limit; the emergency stop; chart series of 31
    days, 12 weeks and 12 months; the edit action and its limits; the last changes."""
    now = _utc(now)
    lim = book.current()
    s = spent(rows, now)

    def line(lid):
        st = lim[lid]
        return st["limitUsd"] if st["enforced"] else None

    windows = {}
    for w in WINDOWS:
        ln = line(f"costs.{w}")
        windows[w] = {"key": window_key(now, w), "spent_usd": float(s[w]), "limit_usd": _f(ln),
                      "left_usd": None if ln is None else float(max(ln - s[w], Decimal("0"))),
                      "tripped": ln is not None and s[w] >= ln}
    emergency = {}
    for w in ("day", "month"):
        st = lim[f"emergency.{w}"]
        emergency[w] = {"limit_usd": _f(st["limitUsd"]), "enforced": st["enforced"],
                        "tripped": st["enforced"] and st["limitUsd"] is not None and s[w] >= st["limitUsd"]}
    return {"schema": SCHEMA, "version": VERSION, "contract": CONTRACT_PIN, "now": _iso(now), "windows": windows,
            "order": {"limit_usd": _f(line("costs.order"))}, "emergency": emergency,
            "unpriced": s["unpriced"], "skipped": s["skipped"],
            "series": {w: series(rows, now, w) for w in WINDOWS},
            "edit": {"action": EDIT_ACTION, "limits": list(LIMIT_IDS),
                     "needs_decision": "raising, clearing or turning off a limit (the operator's words)"},
            "history": limit_changes(book, history),
            "_states": {k: {"limitUsd": _f(v["limitUsd"]), "enforced": v["enforced"]} for k, v in lim.items()},
            "_spent": {w: float(s[w]) for w in WINDOWS}}


def usage_budgets(p, scope="machine"):
    """The panel's limits as the usage report's `budgets[]` (contract DEC-0027 as amended by DEC-0183): every limit
    `editable`; a day, week or month limit with its calendar `period` (`week` since DEC-0183 SL-1); the order's
    limit as `per_job` with no window and `spentUsd` null; the emergency stop as `emergency.day` and
    `emergency.month` (SL-5), `enforced: false` when lifted. A limit with no amount is left out."""
    out = []
    st, sp = p["_states"], p["_spent"]
    for w, kind in (("day", "daily"), ("week", "weekly"), ("month", "monthly")):
        s = st[f"costs.{w}"]
        if s["limitUsd"] is None:
            continue
        e = {"id": f"costs.{w}", "scope": scope, "kind": kind, "period": w, "limitUsd": s["limitUsd"],
             "spentUsd": sp[w], "enforced": s["enforced"], "editable": True}
        if s["enforced"]:
            e["tripped"] = sp[w] >= s["limitUsd"]
        out.append(e)
    s = st["costs.order"]
    if s["limitUsd"] is not None:
        out.append({"id": "costs.order", "scope": "job", "kind": "per_job", "limitUsd": s["limitUsd"], "spentUsd": None,
                    "enforced": s["enforced"], "editable": True})
    for w in ("day", "month"):
        s = st[f"emergency.{w}"]
        if s["limitUsd"] is None:
            continue
        e = {"id": f"emergency.{w}", "scope": scope, "kind": "emergency", "period": w, "limitUsd": s["limitUsd"],
             "spentUsd": sp[w], "enforced": s["enforced"], "editable": True}
        if s["enforced"]:
            e["tripped"] = sp[w] >= s["limitUsd"]
        out.append(e)
    return out


__all__ = ["Refused", "LimitBook", "window_start", "window_key", "money", "spent", "check", "series", "months",
           "panel", "usage_budgets", "limit_changes", "EDIT_ACTION", "READ_ACTION", "LIMIT_IDS", "DEFAULTS",
           "EMERGENCY_DAY_USD", "EMERGENCY_MONTH_USD", "WINDOWS", "SCHEMA", "CHANGE_SCHEMA", "VERSION", "CONTRACT_PIN"]
