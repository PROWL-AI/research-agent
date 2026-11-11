#!/usr/bin/env python3
"""What this agent shipped is never changed or deleted: it is added to (B-105, rule R28).

Operator, 2026-11-11 (board request aed4e06a, agents database rule R28, quoted verbatim in AGENTS.md):
what shipped stays readable and repeatable; a changed entry ships beside the old one under a new version
or name; every change is logged with its reason and basis.

The catalogue of this agent is what shapes a report:

- `runbook/<name>@<version>`: a runbook's `SKILL.md` at the `version` its frontmatter declares. A changed
  runbook bumps `version` and keeps the shipped text beside it as `versions/<old version>.md`, byte for byte
  (the loader reads only `*/SKILL.md`, so an archived version is never offered by mistake).
- `template/<file>`: a report template in `research_agent/report/templates/`. A changed template is a new file.

The lock `catalog/shipped.lock.json` holds the content hash of every entry that ever shipped; it only grows.

    python3 scripts/check_add_only.py                     # exit 1 on any finding
    python3 scripts/check_add_only.py --base origin/main  # also refuse a lock that lost or rehashed a name
    python3 scripts/check_add_only.py --write             # add today's new entries to the lock (never rewrites one)

Retiring an entry keeps it: `catalog/retired.json` maps a name to {"date": "YYYY-MM-DD", "reason": "..."}.
The guard itself is `scripts/add_only.py`, the agents database pattern `add-only-catalog` 1.0.0, unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import add_only  # noqa: E402

LOCK = Path("catalog/shipped.lock.json")
RETIRED = Path("catalog/retired.json")
RUNBOOKS = Path("research_agent/runbooks")
TEMPLATES = Path("research_agent/report/templates")
VERSION = re.compile(r'^version:\s*["\']?([^"\'\s#]+)', re.MULTILINE)


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _version(skill_md: Path) -> str:
    text = skill_md.read_text(encoding="utf-8")
    front = text.split("---", 2)[1] if text.startswith("---") else ""
    found = VERSION.search(front)
    if not found:
        raise ValueError("%s declares no version" % skill_md)
    return found.group(1)


def catalog(root: Path = ROOT) -> Dict[str, Any]:
    """Every entry the tree carries now: current runbooks, their archived versions, report templates."""
    entries: Dict[str, Dict[str, Any]] = {}

    def put(name: str, path: Path) -> None:
        rel = path.relative_to(root).as_posix()
        if name in entries:
            raise ValueError("%s is carried twice: %s and %s" % (name, entries[name]["path"], rel))
        entries[name] = {"sha256": _sha(path), "path": rel}

    for skill_md in sorted((root / RUNBOOKS).glob("*/SKILL.md")):
        put("runbook/%s@%s" % (skill_md.parent.name, _version(skill_md)), skill_md)
        for old in sorted((skill_md.parent / "versions").glob("*.md")):
            put("runbook/%s@%s" % (skill_md.parent.name, old.stem), old)
    for template in sorted((root / TEMPLATES).iterdir()):
        if template.is_file():
            put("template/%s" % template.name, template)
    retired = _read(root / RETIRED)
    for name, mark in retired.items():
        if name in entries:
            entries[name]["retired"] = mark
    # The hash is of the file's bytes alone: moving a shipped text into versions/ keeps its identity.
    return {"entries": {n: {"sha256": e["sha256"], **({"retired": e["retired"]} if "retired" in e else {})}
                        for n, e in entries.items()}}


def _read(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def base_lock(ref: str, root: Path = ROOT) -> Optional[Dict[str, Any]]:
    """The lock in `ref`, or None when that revision has none (the lock's first commit)."""
    shown = subprocess.run(["git", "-C", str(root), "show", "%s:%s" % (ref, LOCK.as_posix())],
                           capture_output=True, text=True)
    if shown.returncode != 0:
        exists = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
                                capture_output=True, text=True)
        if exists.returncode != 0:
            raise ValueError("the base revision %r cannot be read" % ref)
        return None
    return json.loads(shown.stdout)


def findings(root: Path = ROOT, base: Optional[str] = None) -> List[Dict[str, str]]:
    lock = _read(root / LOCK)
    if not lock.get("names"):
        return [add_only.Finding("no-lock", LOCK.as_posix(), "the shipped lock is missing or empty")]
    old = base_lock(base, root) if base else None
    found = add_only.check(catalog(root), lock, old)
    for name in sorted(set(_read(root / RETIRED)) - set(lock["names"])):
        found.append(add_only.Finding("retired-unknown", name, "retired.json names an entry that never shipped"))
    return found


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--write", action="store_true", help="add new entries to the lock; never rewrites one")
    p.add_argument("--base", help="a git revision whose lock this one must keep (lock-rewritten)")
    a = p.parse_args(argv)
    if a.write:
        lock = _read(ROOT / LOCK)
        new = add_only.lock(catalog(), lock)
        problems = add_only.check(catalog(), new, lock or None)
        if problems:
            print(json.dumps(problems, ensure_ascii=False, indent=1))
            return 1
        (ROOT / LOCK).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / LOCK).write_text(json.dumps(new, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        added = sorted(set(new["names"]) - set((lock or {}).get("names") or {}))
        print("locked %d entries (%d new%s)" % (len(new["names"]), len(added), ": " + ", ".join(added) if added else ""))
        return 0
    try:
        found = findings(base=a.base)
    except ValueError as exc:
        print("add-only: cannot check: %s" % exc)
        return 2
    print(json.dumps(found, ensure_ascii=False, indent=1) if found else "add-only: ok")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
