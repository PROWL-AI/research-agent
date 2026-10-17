#!/usr/bin/env python3
"""Run the judge's code checks (no model) over finished runs and count defects.

Usage: python evals/survey_runs.py [runs_root]   (default: runs/)

Prints one JSON row per run with anonymised names (local-1, local-2, …): the
run directories may hold private research, so only counts leave this machine.
Used for docs/evidence/judge-calibration/local-runs-survey.json.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import judge  # noqa: E402

from research_agent.evidence.ledger import Ledger  # noqa: E402
from research_agent.evidence.store import ArtifactStore  # noqa: E402


def survey(root: Path) -> list[dict]:
    rows = []
    for i, run in enumerate(sorted(p for p in root.iterdir() if p.is_dir())):
        if not (run / "report.md").is_file() or not (run / "ledger.json").is_file():
            continue
        checkpoint = ArtifactStore(run).load_checkpoint()
        if checkpoint is None:
            continue
        ledger = Ledger.load(run / "ledger.json")
        defects = judge.code_defects((run / "report.md").read_text(encoding="utf-8"), ledger, checkpoint)
        rows.append({"run": f"local-{i + 1}", "claims": len(ledger.claims), "partial": checkpoint.partial,
                     "defects": dict(Counter(d["kind"] for d in defects))})
    return rows


if __name__ == "__main__":
    rows = survey(Path(sys.argv[1] if len(sys.argv) > 1 else "runs"))
    print(json.dumps(rows, indent=1))
    total: Counter = Counter()
    for row in rows:
        total.update(row["defects"])
    print(json.dumps({"runs": len(rows), "defects": dict(total)}), file=sys.stderr)
