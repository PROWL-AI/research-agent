"""Per-run raw artifact store and checkpointing."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Checkpoint(BaseModel):
    run_id: str
    runbook: str
    status: str = "running"
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    brief: dict[str, Any] = {}
    plan: list[dict[str, Any]] = []
    completed_steps: list[int] = []
    skipped_steps: list[dict[str, Any]] = []
    transform_notes: list[str] = []
    counters: dict[str, Any] = {"data_calls": 0, "cost_usd": None}
    stats: dict[str, Any] = {}
    partial: bool = False
    stop_reason: str | None = None


class ArtifactStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.raw_dir = run_dir / "raw"
        self.checkpoint_path = run_dir / "checkpoint.json"

    def save_raw(self, step_index: int, tool: str, payload: Any) -> Path:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        base = self.raw_dir / f"{step_index:02d}_{tool}.json"
        path = base
        suffix = 1
        while path.exists():
            path = self.raw_dir / f"{step_index:02d}_{tool}_{suffix}.json"
            suffix += 1
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        return path

    def load_raw(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def save_markdown(self, step_index: int, name: str, text: str) -> Path:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        base = self.raw_dir / f"{step_index:02d}_{name}.md"
        path = base
        suffix = 1
        while path.exists():
            path = self.raw_dir / f"{step_index:02d}_{name}_{suffix}.md"
            suffix += 1
        path.write_text(text, encoding="utf-8")
        return path

    def raw_files(self) -> list[Path]:
        if not self.raw_dir.is_dir():
            return []
        return sorted(self.raw_dir.glob("*.json"))

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        checkpoint.updated_at = datetime.now(timezone.utc).isoformat()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path.write_text(
            checkpoint.model_dump_json(indent=2), encoding="utf-8"
        )

    def load_checkpoint(self) -> Checkpoint | None:
        if not self.checkpoint_path.is_file():
            return None
        return Checkpoint.model_validate_json(
            self.checkpoint_path.read_text(encoding="utf-8")
        )
