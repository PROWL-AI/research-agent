"""Seed a throwaway service root with the jobs the dashboard's readability checks need (M1-B).

Usage: python scripts/dashboard-fixtures.py <empty root>

Writes only under <root>: a recent and three older failures, a pending decision, a completed
research job whose run used a limited tool, a tool job of that tool, priced and unpriced calls
and one tutorial job, which every count and list must leave out. No provider is called.
"""

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research_agent.evidence.store import ArtifactStore, Checkpoint, StepRecord
from research_agent.service.store import Store


def stamp(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def main(root: Path) -> None:
    logging.getLogger("research_agent").addHandler(logging.NullHandler())  # no lastResort noise
    store = Store(root)

    def job(request, key, status, phase, days_ago=0.0, **fields):
        record = store.create(request, key)[0]
        if status != "input_required":
            record = store.transition(record["id"], status, phase, **fields)
            record["updatedAt"] = stamp(days_ago)
            store._save(record)
        return record

    research = {"kind": "research", "runbook": "ads-creative-research", "inputs": {"brand": "Example"}}
    job({**research, "inputs": {"brand": "Recent"}}, "fx-recent-failure", "failed", "failed", 0.1,
        error={"code": "timeout", "message": "Wall-clock timeout reached.", "data": {"terminalCode": "cancelled"}})
    for n, code in enumerate(["interrupted", "interrupted", "execution-failed"]):
        job({**research, "inputs": {"brand": f"Old {n}"}}, f"fx-old-failure-{n}", "failed", "interrupted", 5 + n,
            error={"code": code, "message": "Execution interrupted; upstream outcome may be unknown."})
    job({**research, "inputs": {"brand": "Waiting"}}, "fx-pending", "input_required", "awaiting_choice")
    done = job(research, "fx-research-done", "completed", "completed", 0.2,
               result={"output": {"report": "Fixture report."}})
    run = ArtifactStore(root / "runs" / done["id"])
    run.save_checkpoint(Checkpoint(run_id=done["id"], runbook="ads-creative-research", steps=[
        StepRecord(step_id="s-1", raw_index=0, tool="tiktok_ads_library", arguments={"country": "all"}, state="completed")]))
    tool = job({"kind": "tool", "tool": "tiktok_ads_library", "params": {"country": "all"}}, "fx-tool", "completed",
               "completed", 0.2, result={"output": {"rows": [{"ad": "fixture", "country": "FR"}]}})
    job({**research, "inputs": {"brand": "Second"}}, "fx-research-done-2", "completed", "completed", 9,
        result={"output": {"report": "Second fixture report."}})
    # Calls today, 4 and 20 days ago: the three windows read three different sums.
    for record, cost, days_ago in [(done, 0.12, 0), (done, None, 0), (tool, 0.03, 0), (done, 0.5, 4), (done, 2.0, 20)]:
        call = store.start_call(record["id"], "tool", "tiktok_ads_library", {"country": "all"})
        store.finish_call(call, status="completed", costUsd=cost, startedAt=stamp(days_ago),
                          costBasis="provider" if cost is not None else "unknown")
    job({"kind": "tutorial"}, "fx-tutorial-failure", "failed", "failed", 0.1,
        error={"code": "execution-failed", "message": "Tutorial fixture."})
    store.db.close()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
