#!/usr/bin/env python3
"""Measure this agent's metrics (`metrics.json`, agent-metrics/1, rule R31 of the agents database; B-114).

Reads only local files: the service's job store and the run ledgers. Prints one agent-measurement/1 object per metric
with its window, value and n; a value with a small n is still printed, and `metrics.json` says when it is a baseline.

    python scripts/measure_metrics.py [--root <service data folder>] [--runs runs] [--days 7]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path.home() / "Library/Application Support/prowl-research"


def jobs(root: Path, since: str) -> list[dict]:
    db = root / "service.sqlite3"
    if not db.is_file():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = [json.loads(r[0]) for r in con.execute("SELECT body FROM jobs")]
    return [j for j in rows if j.get("request", {}).get("kind") == "research" and j.get("createdAt", "") >= since]


def ledgers(dirs: list[Path]) -> list[list[dict]]:
    out = []
    for d in dirs:
        for f in sorted(d.glob("*/ledger.json")):
            claims = json.loads(f.read_text(encoding="utf-8")).get("claims", [])
            if claims:
                out.append(claims)
    return out


def measure(root: Path, runs: Path, days: int, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    window = {"kind": "rolling", "days": days, "end": now.date().isoformat()}
    terminal = [j for j in jobs(root, since) if j["status"] in {"completed", "failed", "cancelled"}]
    answered = [j for j in terminal if j["status"] == "completed"]
    by_service = [j for j in terminal if j["status"] == "failed" and (j.get("error") or {}).get("code") in {"execution-failed", "interrupted"}]
    claims = [c for ledger in ledgers([runs, root / "runs"]) for c in ledger]
    verified = sum(c.get("status") == "verified" for c in claims)

    def row(metric, value, n, note=None):
        record = {"schema": "agent-measurement/1", "metric": metric, "version": 1, "window": window, "value": value, "n": n}
        return record | ({"note": note} if note else {})

    return [
        row("answered_share", round(len(answered) / len(terminal), 3) if terminal else None, len(terminal)),
        row("verified_claim_share", round(verified / len(claims), 3) if claims else None, len(claims),
            "every run ledger on this machine, not only the window: ledgers carry no creation date"),
        row("failed_by_service_share", round(len(by_service) / len(terminal), 3) if terminal else None, len(terminal)),
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)
    for record in measure(args.root, args.runs, args.days):
        print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
