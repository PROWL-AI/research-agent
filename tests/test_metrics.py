"""B-114 (rule R31): the agent declares the research template's metrics and measures them from local files."""
import json
from datetime import datetime, timezone
from pathlib import Path

import importlib.util

ROOT = Path(__file__).resolve().parents[1]


def test_metrics_cover_outcome_quality_and_reliability_with_a_baseline_or_its_reason():
    data = json.loads((ROOT / "metrics.json").read_text(encoding="utf-8"))
    assert data["schema"] == "agent-metrics/1"
    families = {m["family"] for m in data["metrics"]}
    assert {"outcome", "quality", "reliability"} <= families
    for m in data["metrics"]:
        assert m["baseline"] is not None or m.get("baselineNotMeasured"), m["id"]


def test_the_measurement_script_counts_ledgers_and_jobs(tmp_path):
    spec = importlib.util.spec_from_file_location("measure_metrics", ROOT / "scripts" / "measure_metrics.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    (tmp_path / "runs" / "r1").mkdir(parents=True)
    (tmp_path / "runs" / "r1" / "ledger.json").write_text(json.dumps({"claims": [{"status": "verified"}, {"status": "assumed"}]}))
    rows = {r["metric"]: r for r in mod.measure(tmp_path / "service", tmp_path / "runs", 7, datetime(2026, 11, 13, tzinfo=timezone.utc))}
    assert rows["verified_claim_share"]["value"] == 0.5 and rows["verified_claim_share"]["n"] == 2
    assert rows["answered_share"]["value"] is None and rows["answered_share"]["n"] == 0
