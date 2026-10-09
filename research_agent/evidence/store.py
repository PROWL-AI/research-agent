"""Per-run raw artifact store and checkpointing."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

#: A run_id is a directory name — nothing else. Caller-supplied ids must never
#: escape runs/ via separators or traversal.
RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

#: Directory-name budget: filesystems cap a name at 255 bytes, and a longer
#: caller-supplied id would otherwise fail as an OSError deep in ArtifactStore.
#: The regex above is ASCII-only, so len() == byte length.
MAX_RUN_ID_LENGTH = 128


def validate_run_id(run_id: str) -> str:
    if not RUN_ID_RE.match(run_id) or run_id in (".", ".."):
        raise ValueError(
            f"invalid run_id '{run_id}' — letters, digits, '.', '_', '-' only, no path separators"
        )
    if len(run_id) > MAX_RUN_ID_LENGTH:
        raise ValueError(
            f"invalid run_id — {MAX_RUN_ID_LENGTH} characters max "
            f"(it is a directory name), got {len(run_id)}"
        )
    return run_id


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
        # Atomic: a checkpoint truncated by a crash is an unrecoverable run.
        tmp = self.checkpoint_path.with_suffix(".json.tmp")
        tmp.write_text(checkpoint.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, self.checkpoint_path)

    def load_checkpoint(self) -> Checkpoint | None:
        if not self.checkpoint_path.is_file():
            return None
        return Checkpoint.model_validate_json(
            self.checkpoint_path.read_text(encoding="utf-8")
        )
