"""The Costs section (B-155; rule R33 O16, agents database D-74, pattern `costs-panel` 1.0.0, vendored unchanged).

What this module binds to the service:

- **the rows**: every attempt of the call journal (`Store.cost_rows`), tutorial jobs left out. A call the provider
  priced counts its price; a call without a price counts its worst case in full and is flagged unpriced, never zero
  (a tool call `allowance.TOOL_JOB_WORST_USD`; a model call its tokens at the price table, or, before any token is
  known, `PROMPT_WORST_TOKENS` in and its `max_tokens` out). A call in flight is unpriced, so parallel calls see
  each other.
- **the check before every paid call** (`refusal`): the emergency stop first (USD 500 a UTC day, USD 1000 a calendar
  month, on unless the operator lifts it), then the order's limit against what this job has counted so far, then the
  day, the ISO week and the month. A limit is unset until a person sets it. A refused call is never sent and costs
  nothing; `runtime.ObservedProwl` and `runtime.ObservedLLM` ask before they journal an attempt.
- **the one edit** (`set_limit`, the capability `spend.limits.set` and the dashboard's control alike): tightening is
  the caller's own act; raising, clearing or turning a limit off needs the operator's decision. Every change is a
  line of `spend-limits.jsonl` in the data root, appended and never rewritten.
- **the read** (`panel`, the capability `costs.panel` and the dashboard's section alike). An organization key with the
  scope `costs.read` reads `org_panel` instead (B-162): its own organization's spend and nothing of anyone else's.

It sits beside the allowance (`allowance.py`: a caller's day ceiling and the agents' month ledger decide whether a
job starts without a person); this module decides whether one more paid call may leave.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from research_agent import pricing
from research_agent.service import allowance
from research_agent.service.vendor import costs_panel as cp

#: The limits' book in the data root (the cloud's snapshot keeps it with the job store).
LIMITS_FILE = "spend-limits.jsonl"
#: Prompt tokens assumed for a model call whose tokens are not known yet: an assumption that errs high (a planner
#: prompt with a full evidence block measured well under it), stated here because no call reports it in advance.
PROMPT_WORST_TOKENS = 100_000
#: Output tokens assumed when a call names no `max_tokens`: the largest budget any stage of this agent sets.
OUTPUT_WORST_TOKENS = 16_000
REASONS_RU = {
    "emergency_day": "аварийный стоп за сутки", "emergency_month": "аварийный стоп за месяц",
    "order": "лимит на один запрос", "day": "лимит за сутки", "week": "лимит за неделю", "month": "лимит за месяц",
    "invalid_amount": "стоимость вызова не определена",
}


def book(store) -> cp.LimitBook:
    cached = getattr(store, "_limit_book", None)
    if cached is None:
        cached = store._limit_book = cp.LimitBook(store.root / LIMITS_FILE)
    return cached


def llm_call_worst_usd(model: str, max_tokens: int | None = None) -> float:
    """At most what one model call may cost before its tokens are known. An unknown model is priced at the top of
    the table (`pricing.UNKNOWN_PRICE`), never zero."""
    return pricing.cost_usd(model, PROMPT_WORST_TOKENS, int(max_tokens or OUTPUT_WORST_TOKENS))[0]


def worst_of(call: dict[str, Any]) -> float:
    """The worst case of a journaled call the provider did not price."""
    if call["kind"] == "tool":
        return allowance.TOOL_JOB_WORST_USD
    if call.get("inputTokens") or call.get("outputTokens"):
        return pricing.cost_usd(call["name"], int(call.get("inputTokens") or 0), int(call.get("outputTokens") or 0))[0]
    return llm_call_worst_usd(call["name"], call.get("maxTokens"))


def rows(store, since: datetime | None = None, job: str | None = None) -> list[dict[str, Any]]:
    """The pattern's rows: `{at, usd}` for a priced call, `{at, usd: None, worst_usd}` for an unpriced one."""
    out = []
    for call in store.cost_rows(since.strftime("%Y-%m-%dT%H:%M:%S") if since else None, job):
        row: dict[str, Any] = {"at": call["at"], "usd": call["costUsd"], "job": call["job"]}
        if call["costUsd"] is None:
            row["worst_usd"] = worst_of(call)
        out.append(row)
    return out


def _counted(row: dict[str, Any]) -> Decimal:
    return cp.money(row["usd"] if row["usd"] is not None else row["worst_usd"])


def check_call(store, job: dict[str, Any], amount_usd: float, now: datetime | None = None) -> dict[str, Any]:
    """The pattern's verdict for one more paid call of `amount_usd` (its worst case) inside `job`."""
    now = now or datetime.now(timezone.utc)
    since = min(cp.window_start(now, "week"), cp.window_start(now, "month"))
    limits = book(store).current()
    spent = cp.spent(rows(store, since), now)
    order = limits["costs.order"]
    # the order's line is read against what this job has counted, not against one call (below)
    windows_only = {**limits, "costs.order": {"limitUsd": None, "enforced": order["enforced"]}}
    verdict = cp.check({w: spent[w] for w in cp.WINDOWS}, amount_usd, windows_only)
    if verdict["allowed"] and order["limitUsd"] is not None and order["enforced"]:
        counted = sum((_counted(r) for r in rows(store, None, job["id"])), Decimal("0"))
        if counted + verdict["amount_usd"] > order["limitUsd"]:
            verdict = {"allowed": False, "reason": "order", "window": None, "limit_usd": order["limitUsd"],
                       "spent_usd": counted, "amount_usd": verdict["amount_usd"]}
    return verdict


def refusal(store, job: dict[str, Any], amount_usd: float) -> str | None:
    """None when the call may leave; else why not, for the caller (English) with one dashboard event per job and
    limit (Russian). A journal or a book that cannot be read refuses: a call that cannot be checked is not sent."""
    try:
        verdict = check_call(store, job, amount_usd)
    except Exception as exc:  # noqa: BLE001 - an unreadable journal or book: nothing is sent
        return f"Spend limits cannot be checked ({type(exc).__name__})"
    if verdict["allowed"]:
        return None
    reason = verdict["reason"]
    limit, spent = verdict["limit_usd"], verdict["spent_usd"]
    seen = store.__dict__.setdefault("_limit_notified", set())
    if (job["id"], reason) not in seen:
        seen.add((job["id"], reason))
        text = f"Платный вызов не отправлен: {REASONS_RU.get(reason, reason)}"
        if limit is not None and spent is not None:
            text += f", учтено {float(spent):.2f} из {float(limit):.2f} USD"
        with store.db:
            store.event("costs.limit_reached", text + ". Лимиты меняются в разделе «Расходы».", job, "notice",
                        reason.startswith("emergency"))
    if limit is None or spent is None:
        return f"Spend limit reached ({reason})"
    return f"Spend limit reached ({reason}: {float(spent):.2f} of {float(limit):.2f} USD counted)"


def panel(store, now: datetime | None = None) -> dict[str, Any]:
    """`costs.panel` (schema `costs-panel/1`): the windows with spent, limit, left and tripped, the order's limit,
    the emergency stop, chart series of 31 days, 12 weeks and 12 months, the edit action, the last changes, and the
    limits' own state under `limits`."""
    now = now or datetime.now(timezone.utc)
    start = cp.window_start(now, "month")
    for _ in range(12):
        start = cp._step_back(start, "month")
    data = cp.panel(rows(store, start), book(store), now)
    data["limits"] = data.pop("_states")
    data.pop("_spent")
    return data


def set_limit(store, args: dict[str, Any], *, via: str, decision: dict[str, Any] | None = None,
              by_ref: str | None = None) -> dict[str, Any]:
    """`spend.limits.set`: one limit's amount, its `enforced`, or both. Raises the pattern's `Refused`."""
    extra: dict[str, Any] = {}
    if "limitUsd" in args:
        extra["limit_usd"] = args["limitUsd"]
    result = book(store).set(args.get("limitId"), enforced=args.get("enforced"), reason=args.get("reason"),
                             idempotency_key=args.get("idempotencyKey"), via=via, decision=decision, by_ref=by_ref,
                             **extra)
    change = result["change"]
    if change is not None and not result["repeated"]:
        after = change["after"]
        amount = "без суммы" if after["limitUsd"] is None else f"{after['limitUsd']:g} USD"
        state = "действует" if after["enforced"] else "выключен"
        with store.db:
            store.event("costs.limit_changed", f"Лимит расходов {change['limitId']} изменён: {amount}, {state}.")
    return result


#: What an organization's read leaves out of the operator's panel (B-162): the edit is the operator's, and the
#: history of limit changes carries the operator's reasons, not an organization's business.
ORG_DROPPED = ("edit", "history")


def org_panel(store, delegation: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """`costs.panel` for an organization key (B-162, scope `costs.read`): the same windows and chart series counted
    over the organization's own jobs only (`org:<org>`), its monthly ceiling with what it has spent and has left, and
    the emergency stop as it stands for the whole instance (a stop explains a refused call). The instance's window
    limits, its spend, the edit and the change history are the operator's and are not shown."""
    now = now or datetime.now(timezone.utc)
    principal = str(delegation.get("principal") or "")
    if not principal.startswith("org:"):
        raise ValueError("an organization's spend is read with an organization key")
    start = cp.window_start(now, "month")
    for _ in range(12):
        start = cp._step_back(start, "month")
    own = {j["id"] for j in store.jobs() if allowance.principal_of(j) == principal}
    mine = [r for r in rows(store, start) if r["job"] in own]
    data = cp.panel(mine, book(store), now)
    whole = cp.panel(rows(store, min(cp.window_start(now, "day"), cp.window_start(now, "month"))), book(store), now)
    for key in ORG_DROPPED + ("_states", "_spent"):
        data.pop(key, None)
    for window in data["windows"].values():  # the instance's own window limits are not the organization's
        window.update(limit_usd=None, left_usd=None, tripped=False)
    data["order"] = {"limit_usd": None}
    data["emergency"] = whole["emergency"]
    monthly = float(delegation.get("monthlyUsd") or 0.0)
    spent = allowance.spent_this_month(store, principal, now.strftime("%Y-%m"))
    data["scope"] = {"kind": "organization", "organization": principal[len("org:"):]}
    data["organization"] = {"organization": principal[len("org:"):], "month": now.strftime("%Y-%m"),
                            "monthlyCeilingUsd": monthly, "spentMonthUsd": round(spent, 4),
                            "leftMonthUsd": round(max(monthly - spent, 0.0), 4),
                            "counted": "approved jobs of the organization, at cost; a job still running at its worst case"}
    return data
