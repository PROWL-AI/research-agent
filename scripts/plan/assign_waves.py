#!/usr/bin/env python3
"""Assign every inventory item its wave and release from one node→wave table.

The inventory (docs/specs/2026-10-11-waves-inventory.json) is authored by hand
with an `id`, `source`, `status`, `area` and `node` per open item. This script
owns the other two fields: it writes `wave` and `release` onto every entry from
the table below, then prints the counts per wave and per node. A re-cut is a diff
to WAVE_OF_NODE plus a re-run — never hand edits across the inventory.

Usage:
    python3 scripts/plan/assign_waves.py          # rewrite the inventory, print counts
    python3 scripts/plan/assign_waves.py --check  # exit 1 if the file is not what the table yields
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

INVENTORY = Path(__file__).resolve().parents[2] / "docs/specs/2026-10-11-waves-inventory.json"

# node → wave. `None` keeps a node outside this release's waves; its items carry
# the release named in RELEASE_OF_NODE instead.
WAVE_OF_NODE: dict[str, int | None] = {
    "N-OWN": 1,     # run ownership: every lifecycle write behind the run lock
    "N-DOCS": 1,    # docs honesty, core scenarios, wiki card, CI, probe harness
    "N-STATE": 2,   # checkpoint v2: immutable step identity, step state machine, durability, migration
    "N-COST": 2,    # attempt ledger: per-attempt actual/estimate/unknown, persisted in finally
    "N-EVID": 3,    # ledger v2: group recompute, quote-to-raw, source identity
    "N-LLMB": 4,    # LLM budget on the attempt ledger
    "N-SVC": 4,     # service runtime parity with the CLI/MCP clients
    "N-FAB": 5,     # Fabric contract: pin, delegation callee, Observatory launch, kit
    "N-ACC": 6,     # live acceptance: judge calibration, paid runs, native host, admission
    "N-EXT": None,  # owned by another repository or session
    "N-PROG": None, # waits on an external decision; stays on the canvas
}
RELEASE_OF_NODE = {"N-EXT": "external", "N-PROG": "program"}


def assign(items: list[dict]) -> list[str]:
    errors = []
    for item in items:
        node = item.get("node")
        if node not in WAVE_OF_NODE:
            errors.append(f"{item.get('id')}: node {node!r} is not in WAVE_OF_NODE")
            continue
        wave = WAVE_OF_NODE[node]
        item["wave"] = wave
        item["release"] = RELEASE_OF_NODE.get(node, "this")
    ids = [i.get("id") for i in items]
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    if dupes:
        errors.append(f"duplicate ids: {dupes}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    doc = json.loads(INVENTORY.read_text(encoding="utf-8"))
    before = json.dumps(doc, ensure_ascii=False, indent=2)
    errors = assign(doc["items"])
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    after = json.dumps(doc, ensure_ascii=False, indent=2)
    if args.check:
        if before != after:
            print("inventory is stale: run scripts/plan/assign_waves.py", file=sys.stderr)
            return 1
    else:
        INVENTORY.write_text(after + "\n", encoding="utf-8")
    per_wave = Counter(str(i["wave"]) if i["wave"] is not None else i["release"] for i in doc["items"])
    per_node = Counter(i["node"] for i in doc["items"])
    print("per wave:", ", ".join(f"{k}={v}" for k, v in sorted(per_wave.items())))
    print("per node:", ", ".join(f"{k}={v}" for k, v in sorted(per_node.items())))
    print("open:", sum(1 for i in doc["items"] if i["status"] not in ("closed", "dropped")), "of", len(doc["items"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
