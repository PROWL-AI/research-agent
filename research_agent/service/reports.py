"""An organization's report memory (B-160).

The operator's word of 2026-11-23 (relayed by the Fabric CEO, board request 39a22ae6): «у каждой организации будет
свой собственный ключ и своя собственная память для всех этих репортов, которые запускаются. Они общие, чтобы люди
могли эти репорты потом переиспользовать. Запустивший один репорт сохраняет его, и потом другие могут тоже его
видеть, забирать и так далее, чтобы не было пересечения.»

- Every job an organization key starts belongs to `org:<org>` (the principal), so every holder of that
  organization's key lists, reads and resumes it, and no other organization does (`delegation.owned_by`).
- `listing` is the memory: the organization's finished research reports, newest first, with who ran each.
- `ready_report` is the check before a new paid run: a completed run of the same runbook with the same inputs
  (compared without case and outer spaces), with its report on disk, younger than `REUSE_DAYS`, is answered instead
  of starting a new one. The caller who really wants a new run says `fresh: true`.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from research_agent.service.delegation import ORG_PRINCIPAL

#: How old a ready report may be and still answer a new request for the same research (days).
REUSE_DAYS = 30
#: The most reports one listing answers.
LIST_LIMIT = 100


def _norm(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    if isinstance(value, dict):
        return {str(k): _norm(v) for k, v in value.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def research_key(runbook: str, inputs: dict[str, Any] | None) -> str:
    """The identity of a piece of research: its runbook and its inputs, without case, spacing or empty fields."""
    return json.dumps({"runbook": runbook, "inputs": _norm(inputs or {})}, sort_keys=True, ensure_ascii=False)


def is_org(delegation: dict[str, Any] | None) -> bool:
    return str((delegation or {}).get("principal") or "").startswith(ORG_PRINCIPAL)


def _principal(job: dict[str, Any]) -> str | None:
    owner = job.get("chainOwner") or job.get("delegation") or {}
    return owner.get("principal")


def _has_report(store, job: dict[str, Any]) -> bool:
    from research_agent.service.runtime import run_dir_name  # runtime imports this module

    path = store.root / "runs" / run_dir_name(job) / "report.md"
    return path.is_file() and not path.is_symlink()


def _parse(stamp: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def _finished(store, principal: str) -> list[dict[str, Any]]:
    return [j for j in store.jobs()
            if _principal(j) == principal and j.get("status") == "completed"
            and (j.get("request") or {}).get("kind") == "research" and _has_report(store, j)]


def ready_report(store, delegation: dict[str, Any] | None, request: dict[str, Any],
                 now: datetime | None = None) -> dict[str, Any] | None:
    """The organization's newest completed run of this research with its report, or None."""
    if not is_org(delegation) or request.get("kind") != "research" or request.get("resumeJobId") or request.get("fresh"):
        return None
    wanted = research_key(request["runbook"], request.get("inputs"))
    oldest = (now or datetime.now(timezone.utc)) - timedelta(days=REUSE_DAYS)
    for job in _finished(store, delegation["principal"]):  # newest first (store.jobs order)
        at = _parse(job.get("updatedAt"))
        if at is None or at < oldest:
            continue
        if research_key(job["request"]["runbook"], job["request"].get("inputs")) == wanted:
            return job
    return None


def summary(job: dict[str, Any]) -> dict[str, Any]:
    request = job.get("request") or {}
    caller = ((job.get("delegation") or {}).get("caller") or "")
    return {"id": job["id"], "runbook": request.get("runbook"), "inputs": request.get("inputs") or {},
            "completedAt": job.get("updatedAt"), "createdAt": job.get("createdAt"),
            "by": caller.split(":", 1)[-1] or None, "artifacts": ["report.md", "ledger.json", "result.json"]}


def listing(store, delegation: dict[str, Any] | None, runbook: str | None = None, query: str | None = None,
            limit: int = LIST_LIMIT) -> dict[str, Any]:
    """The caller's organization's finished reports, newest first. A key of no organization lists its own."""
    principal = (delegation or {}).get("principal")
    if not principal:
        return {"organization": None, "reports": []}
    words = _norm(query or "").split()
    reports = []
    for job in _finished(store, principal):
        if runbook and job["request"].get("runbook") != runbook:
            continue
        if words:
            text = research_key(job["request"]["runbook"], job["request"].get("inputs"))
            if not all(w in text for w in words):
                continue
        reports.append(summary(job))
        if len(reports) >= max(1, min(int(limit), LIST_LIMIT)):
            break
    org = principal[len(ORG_PRINCIPAL):] if principal.startswith(ORG_PRINCIPAL) else None
    return {"organization": org, "reports": reports, "reuseDays": REUSE_DAYS}
