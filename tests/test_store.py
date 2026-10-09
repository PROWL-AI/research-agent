"""ArtifactStore persistence: atomic writes, strict JSON, schema versioning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent.evidence.store import ArtifactStore, Checkpoint


class TestSaveRawIsAtomic:
    def test_save_raw_leaves_no_partial_file(self, tmp_path: Path):
        store = ArtifactStore(tmp_path / "run1")
        path = store.save_raw(0, "some_tool", {"rows": [1, 2, 3]})
        assert path.is_file()
        assert not list(store.raw_dir.glob("*.tmp"))
        assert json.loads(path.read_text()) == {"rows": [1, 2, 3]}

    def test_save_raw_rejects_non_finite_numbers(self, tmp_path: Path):
        store = ArtifactStore(tmp_path / "run1")
        with pytest.raises(ValueError):
            store.save_raw(0, "some_tool", {"value": float("nan")})
        assert not list(store.raw_dir.glob("*.json"))


class TestCheckpointStrictJson:
    def test_save_checkpoint_rejects_non_finite_counters(self, tmp_path: Path):
        store = ArtifactStore(tmp_path / "run1")
        checkpoint = Checkpoint(run_id="run1", runbook="x")
        checkpoint.counters["cost_usd"] = float("inf")
        with pytest.raises(ValueError):
            store.save_checkpoint(checkpoint)
        assert not store.checkpoint_path.exists()


class TestCheckpointSchemaVersion:
    def test_saved_checkpoint_carries_schema_version(self, tmp_path: Path):
        store = ArtifactStore(tmp_path / "run1")
        store.save_checkpoint(Checkpoint(run_id="run1", runbook="x"))
        data = json.loads(store.checkpoint_path.read_text())
        assert data["schema_version"] == 1

    def test_checkpoint_without_schema_version_still_loads(self, tmp_path: Path):
        # Pre-versioning checkpoints stay resumable.
        run_dir = tmp_path / "run1"
        run_dir.mkdir(parents=True)
        (run_dir / "checkpoint.json").write_text(json.dumps({
            "run_id": "run1",
            "runbook": "x",
            "plan": [{"step": "s", "tool": "t"}],
        }))
        store = ArtifactStore(run_dir)
        checkpoint = store.load_checkpoint()
        assert checkpoint is not None
        assert checkpoint.schema_version == 1
        assert checkpoint.run_id == "run1"
