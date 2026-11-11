"""Add-only catalogue guard: what an agent already shipped (generations, recipes, scenarios, formats, styles,
prompts) is never changed or deleted; a changed entry ships beside the old one under a new name or version; an entry
leaves only through a `retired` mark with its date and reason; every change is logged with its reason and basis; a
change is accepted only when a before/after reading proves it no worse. Standard library only.

    python3 add_only.py lock  --catalog catalog.json --lock shipped.lock.json   # record new names; never rewrites one
    python3 add_only.py check --catalog catalog.json --lock shipped.lock.json   # exit 1 on any finding

The catalogue is JSON: {"entries": {"<name>": {...}}}. An entry carrying {"retired": {"date": "YYYY-MM-DD",
"reason": "..."}} is retired: it stays in the catalogue, readable and repeatable, and is no longer offered.
Operator, 2026-11-11: «мы всегда только добавили, чтобы всегда можно было посмотреть ... только улучшали и все
изменения были логированы».
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

__version__ = "1.0.0"

LOCK_SCHEMA = "add-only-lock/1"
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Finding(dict):
    """A typed finding: {"code", "name", "detail"}. Codes: missing, changed, retired-incomplete, lock-rewritten,
    replaces-base, row-missing, no-changelog, log-incomplete, no-proof, worse."""

    def __init__(self, code: str, name: str, detail: str):
        super().__init__(code=code, name=name, detail=detail)


def digest(entry: Mapping[str, Any]) -> str:
    """The content hash of an entry without its `retired` mark (retiring an entry does not change what it was)."""
    body = {k: v for k, v in entry.items() if k != "retired"}
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def entries_of(catalog: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    entries = catalog.get("entries") if isinstance(catalog, Mapping) else None
    if not isinstance(entries, Mapping):
        raise ValueError("a catalogue is {\"entries\": {name: entry}}")
    for name, entry in entries.items():
        if not isinstance(name, str) or not name or not isinstance(entry, Mapping):
            raise ValueError("every entry has a non-empty name and an object body")
    return dict(entries)


def retired_ok(mark: Any) -> bool:
    return (isinstance(mark, Mapping) and isinstance(mark.get("date"), str) and bool(DATE.match(mark["date"]))
            and isinstance(mark.get("reason"), str) and bool(mark["reason"].strip()))


def lock(catalog: Mapping[str, Any], old_lock: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The lock after this catalogue ships: every name already locked keeps its hash; new names are added. A lock
    never forgets a name, so a deletion is always visible to `check`."""
    names = dict((old_lock or {}).get("names") or {})
    for name, entry in sorted(entries_of(catalog).items()):
        names.setdefault(name, digest(entry))
    return {"schema": LOCK_SCHEMA, "names": dict(sorted(names.items()))}


def check(catalog: Mapping[str, Any], shipped_lock: Mapping[str, Any],
          base_lock: Optional[Mapping[str, Any]] = None) -> List[Finding]:
    """Findings for a catalogue against the lock of what shipped. `base_lock` is the lock in the revision the change
    starts from: a name it held that the new lock dropped or rehashed is `lock-rewritten`."""
    findings: List[Finding] = []
    entries = entries_of(catalog)
    locked = dict(shipped_lock.get("names") or {})
    for name, was in sorted(((base_lock or {}).get("names") or {}).items()):
        if locked.get(name) != was:
            findings.append(Finding("lock-rewritten", name, "the shipped lock lost or rehashed this name"))
    for name, was in sorted(locked.items()):
        entry = entries.get(name)
        if entry is None:
            findings.append(Finding("missing", name, "a shipped entry was deleted; retire it instead"))
            continue
        if digest(entry) != was:
            findings.append(Finding("changed", name, "a shipped entry was edited; add the change under a new name "
                                                     "or version and keep this one"))
    for name, entry in sorted(entries.items()):
        if "retired" in entry and not retired_ok(entry["retired"]):
            findings.append(Finding("retired-incomplete", name, "retired needs a date (YYYY-MM-DD) and a reason"))
    return findings


def check_overlay(base: Mapping[str, Any], overlay: Mapping[str, Any], merged: Mapping[str, Any],
                  changelog: str) -> List[Finding]:
    """An organization's overlay on the base catalogue: it may add, never replace a base entry, the merged catalogue
    keeps every base row, and an overlay with entries is named in the copy's CHANGELOG."""
    findings: List[Finding] = []
    b, o, m = entries_of(base), entries_of(overlay), entries_of(merged)
    for name in sorted(set(b) & set(o)):
        if digest(o[name]) != digest(b[name]):
            findings.append(Finding("replaces-base", name, "the overlay replaces a base entry; add it under a new name"))
    for name in sorted(set(b) - set(m)):
        findings.append(Finding("row-missing", name, "the merged catalogue lost a base row"))
    for name in sorted(set(o) - set(b)):
        if name not in changelog:
            findings.append(Finding("no-changelog", name, "an overlay entry the CHANGELOG does not name"))
    return findings


LOG_FIELDS = ("date", "what", "reason", "basis", "by")
AUTHORS = ("agent", "person")


def check_log(rows: Iterable[Mapping[str, Any]]) -> List[Finding]:
    """Every change-log row says when, what, why, on what basis (a test, an acceptance, a measurement, a decision)
    and who made it: an agent or a person of the organization."""
    findings: List[Finding] = []
    for i, row in enumerate(rows):
        missing = [k for k in LOG_FIELDS if not (isinstance(row.get(k), str) and row[k].strip())]
        if not missing and row["by"].split(":", 1)[0] not in AUTHORS:
            missing = ["by (agent:<name> or person:<role>)"]
        if not missing and not DATE.match(row["date"]):
            missing = ["date (YYYY-MM-DD)"]
        if missing:
            findings.append(Finding("log-incomplete", str(row.get("what") or i), "lacks " + ", ".join(missing)))
    return findings


def judge(before: Mapping[str, float], after: Mapping[str, float], higher_is_better: Mapping[str, bool]) -> str:
    """`accept` when every measured metric is no worse after and at least one is better, `rollback` when any is
    worse (a regression is rolled back first), `no-proof` when a metric has no reading on both sides or none moved."""
    if not higher_is_better:
        return "no-proof"
    better = False
    for metric, up in higher_is_better.items():
        if metric not in before or metric not in after:
            return "no-proof"
        delta = (after[metric] - before[metric]) * (1 if up else -1)
        if delta < 0:
            return "rollback"
        better = better or delta > 0
    return "accept" if better else "no-proof"


def _read(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("command", choices=("lock", "check"))
    p.add_argument("--catalog", required=True, type=Path)
    p.add_argument("--lock", required=True, type=Path)
    a = p.parse_args(argv)
    catalog = _read(a.catalog)
    if a.command == "lock":
        new = lock(catalog, _read(a.lock))
        findings = check(catalog, new, _read(a.lock))
        if findings:
            print(json.dumps(findings, ensure_ascii=False, indent=1))
            return 1
        a.lock.write_text(json.dumps(new, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("locked %d names" % len(new["names"]))
        return 0
    findings = check(catalog, _read(a.lock))
    print(json.dumps(findings, ensure_ascii=False, indent=1) if findings else "add-only: ok")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
