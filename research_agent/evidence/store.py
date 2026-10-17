"""Per-run raw artifact store and checkpointing."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from pydantic import BaseModel, Field

from research_agent.evidence.ledger import _atomic_write_text

#: Written into every checkpoint.json. Version 1 checkpoints (and pre-versioning
#: ones) are migrated on load by research_agent.evidence.migrate.
SCHEMA_VERSION = 2

#: A run_id is a directory name — nothing else. Caller-supplied ids must never
#: escape runs/ via separators or traversal.
RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

#: Directory-name budget: filesystems cap a name at 255 bytes, and a longer
#: caller-supplied id would otherwise fail as an OSError deep in ArtifactStore.
#: The regex above is ASCII-only, so len() == byte length.
MAX_RUN_ID_LENGTH = 128

#: Step states (docs/specs/2026-10-11-waves-canvas.md §2 N-STATE).
PENDING = "pending"
DISPATCHING = "dispatching"
OUTCOME_UNKNOWN = "outcome_unknown"
RAW_SAVED = "raw_saved"
COMPLETED = "completed"
FAILED = "failed"
SKIPPED_ON_ERROR = "skipped_on_error"
SKIPPED_BUDGET = "skipped_budget"
EXCLUDED = "excluded"
STEP_STATES = frozenset({
    PENDING, DISPATCHING, OUTCOME_UNKNOWN, RAW_SAVED, COMPLETED,
    FAILED, SKIPPED_ON_ERROR, SKIPPED_BUDGET, EXCLUDED,
})
#: States a resume never re-executes.
SETTLED_STATES = frozenset({COMPLETED, SKIPPED_ON_ERROR, SKIPPED_BUDGET, EXCLUDED})


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def make_step_id(raw_index: int, tool: str, arguments: dict[str, Any]) -> str:
    """A step's identity, assigned once when the plan is made and never
    re-derived: catalog or allowlist changes between attempts cannot shift it."""
    digest = hashlib.sha256(
        canonical_json({"raw_index": raw_index, "tool": tool, "arguments": arguments}).encode()
    ).hexdigest()
    return "s-" + digest[:12]


class StepRecord(BaseModel):
    step_id: str
    raw_index: int
    kind: str = "data"  # data | transform
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    step: str = ""
    instruction: str | None = None
    on_error_skip: bool = False
    state: str = PENDING
    reason: str | None = None
    #: Run-dir-relative ("raw/<step_id>_<tool>.json") — portable across CLI,
    #: stdio MCP and the service, which run from different working directories.
    raw_ref: str | None = None
    raw_sha256: str | None = None
    extraction: dict[str, Any] = Field(
        default_factory=lambda: {"status": "pending", "error": None, "claim_ids": []}
    )
    attempt_ids: list[str] = Field(default_factory=list)
    #: The v1 idempotency key (`run:index:tool`) of a step migrated from a v1
    #: checkpoint whose dispatch may have reached the server; used for the
    #: step's first resend only.
    legacy_key: str | None = None


class AttemptRecord(BaseModel):
    """One dispatch (tool) or model call (llm). Appended before the call and
    finalized in a finally block, so a billed failure or a crash mid-call never
    loses its cost."""

    attempt_id: str
    step_id: str
    kind: str = "tool"  # tool | llm
    attempt_no: int = 1
    idempotency_key: str | None = None
    started_at: str = Field(default_factory=_now)
    ended_at: str | None = None
    outcome: str = "pending"  # pending | ok | refused | transport_error | cancelled | unknown
    cost_basis: str = "unknown"  # actual | estimate | unknown
    actual_usd: float | None = None
    estimate_usd: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    model: str | None = None

    @property
    def spend_usd(self) -> float:
        if self.actual_usd is not None:
            return self.actual_usd
        return self.estimate_usd or 0.0


class Checkpoint(BaseModel):
    run_id: str
    runbook: str
    schema_version: int = SCHEMA_VERSION
    status: str = "running"
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    brief: dict[str, Any] = {}
    #: The plan as the planner returned it (before validation).
    plan_raw: list[dict[str, Any]] = []
    #: The plan as executed: every planned item, validated once; drops are
    #: `excluded` steps with the validator's reason.
    steps: list[StepRecord] = []
    attempts: list[AttemptRecord] = []
    transform_notes: list[str] = []
    stats: dict[str, Any] = {}
    partial: bool = False
    stop_reason: str | None = None
    #: Why the run reached its terminal status — research_agent.evidence.terminal.
    terminal_code: str | None = None
    migrated_from: int | None = None
    #: The run's resolved LLM ceiling (USD), recorded at start so a resume
    #: keeps it unless the caller or the environment says otherwise.
    llm_cap_usd: float | None = None

    # ── views (read-only; never persisted) ──────────────────────────────────

    def step(self, step_id: str) -> StepRecord:
        for record in self.steps:
            if record.step_id == step_id:
                return record
        raise KeyError(step_id)

    def step_counts(self) -> dict[str, int]:
        counts = {state: 0 for state in sorted(STEP_STATES)}
        for record in self.steps:
            counts[record.state] = counts.get(record.state, 0) + 1
        return counts

    def completed_step_ids(self) -> list[str]:
        return [s.step_id for s in self.steps if s.state == COMPLETED]

    @property
    def planned_steps(self) -> int:
        return sum(1 for s in self.steps if s.state != EXCLUDED)

    @property
    def completed_steps(self) -> list[str]:
        return self.completed_step_ids()

    #: States of a step that is still being worked on while a run is live.
    _IN_FLIGHT = frozenset({PENDING, DISPATCHING, RAW_SAVED, OUTCOME_UNKNOWN})

    def disclosures(self, final: bool) -> list[dict[str, Any]]:
        """Steps the report or a status reader must see as missing or not run.

        final=True (the writer, a terminal checkpoint): everything not
        `completed`, except `pending` steps of a run that did not stop.
        final=False (a live run): only settled omissions and stops — steps
        still in flight are progress, not disclosures."""
        disclosed = []
        for s in self.steps:
            if s.state == COMPLETED:
                continue
            if not final and s.state in self._IN_FLIGHT and self.stop_reason is None:
                continue
            if s.state == PENDING:
                if self.stop_reason is None:
                    continue
                disclosed.append(self._disclosure(s, s.reason or self.stop_reason))
                continue
            disclosed.append(self._disclosure(s, s.reason or s.state))
        return disclosed

    @property
    def skipped_steps(self) -> list[dict[str, Any]]:
        return self.disclosures(final=self.status != "running")

    @staticmethod
    def _disclosure(s: StepRecord, reason: str) -> dict[str, Any]:
        return {"step_id": s.step_id, "index": s.raw_index, "step": s.step, "tool": s.tool,
                "reason": reason, "state": s.state}

    def tool_attempts(self) -> list[AttemptRecord]:
        return [a for a in self.attempts if a.kind == "tool"]

    def spend_usd(self, kind: str = "tool") -> float:
        """Σ actual + Σ estimate for attempts without an actual. An unknown
        cost counts at its estimate — never as zero."""
        return round(sum(a.spend_usd for a in self.attempts if a.kind == kind), 6)

    def unknown_attempts(self, kind: str = "tool") -> int:
        return sum(1 for a in self.attempts if a.kind == kind and a.cost_basis == "unknown")

    def cost_source(self, kind: str = "tool") -> str | None:
        bases = {a.cost_basis for a in self.attempts if a.kind == kind}
        if not bases:
            return None
        if bases == {"actual"}:
            return "server"
        if "actual" in bases:
            return "mixed"
        return "estimate"

    @property
    def counters(self) -> Mapping[str, Any]:
        """Derived from the attempt ledger; read-only (a write would vanish)."""
        tool = self.tool_attempts()
        actual = [a.actual_usd for a in tool if a.actual_usd is not None]
        estimated = [a.estimate_usd or 0.0 for a in tool if a.actual_usd is None]
        return MappingProxyType({
            "data_calls": sum(1 for a in tool if a.outcome == "ok"),
            "attempted_calls": len(tool),
            "cost_usd": round(sum(actual), 6) if actual else None,
            "cost_estimate_usd": round(sum(estimated), 6) if estimated else None,
            "spend_usd": self.spend_usd("tool"),
            "cost_unknown_attempts": self.unknown_attempts("tool"),
        })

    def live_stats(self) -> dict[str, Any]:
        """The stats keys that follow the ledger and the steps — refreshed on
        every save, so a reader mid-run (or of a migrated run) never sees an
        earlier attempt's numbers."""
        counters = dict(self.counters)
        return {**counters, "cost_source": self.cost_source("tool"), "steps": self.step_counts()}


class CheckpointMigrationError(ValueError):
    """A v1 checkpoint whose state cannot be mapped to steps without guessing.
    The run is reported as needing attention and is never silently resumed."""


class ArtifactStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.raw_dir = run_dir / "raw"
        self.checkpoint_path = run_dir / "checkpoint.json"

    def save_raw(self, step_id: str, tool: str, payload: Any) -> tuple[str, str]:
        """Write one step's raw payload atomically; returns (raw_ref, sha256).
        The name is the step's identity, so a re-dispatch replaces — never
        duplicates — the step's raw."""
        text = json.dumps(payload, indent=2, ensure_ascii=False, default=str, allow_nan=False)
        return self._write_artifact(f"{step_id}_{tool}.json", text)

    def save_markdown(self, step_id: str, name: str, text: str) -> tuple[str, str]:
        return self._write_artifact(f"{step_id}_{name}.md", text)

    def _write_artifact(self, name: str, text: str) -> tuple[str, str]:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(self.raw_dir / name, text)
        return f"raw/{name}", hashlib.sha256(text.encode("utf-8")).hexdigest()

    def resolve(self, raw_ref: str) -> Path:
        """Absolute path of a run-dir-relative ref (absolute refs from v1 are
        returned as they are)."""
        path = Path(raw_ref)
        return path if path.is_absolute() else self.run_dir / path

    def read_artifact(self, raw_ref: str, expected_sha256: str | None = None) -> str:
        text = self.resolve(raw_ref).read_text(encoding="utf-8")
        if expected_sha256 is not None:
            actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if actual != expected_sha256:
                raise ValueError(f"artifact {raw_ref} does not match its recorded sha256")
        return text

    def load_raw(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def raw_files(self) -> list[Path]:
        if not self.raw_dir.is_dir():
            return []
        return sorted(self.raw_dir.glob("*.json"))

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        checkpoint.updated_at = datetime.now(timezone.utc).isoformat()
        checkpoint.stats = {**checkpoint.stats, **checkpoint.live_stats()}
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if checkpoint.migrated_from == 1 and self.checkpoint_path.is_file():
            # The first save of a migrated run keeps the v1 file beside it: a
            # rollback to a v1 build reads that, instead of re-planning (and
            # re-billing) a v2 checkpoint it cannot understand.
            backup = self.run_dir / "checkpoint.v1.json"
            if not backup.exists():
                try:
                    if int(json.loads(self.checkpoint_path.read_text(encoding="utf-8")).get("schema_version") or 1) < 2:
                        backup.write_text(self.checkpoint_path.read_text(encoding="utf-8"), encoding="utf-8")
                except (OSError, ValueError):
                    pass
        # Atomic: a checkpoint truncated by a crash is an unrecoverable run.
        # allow_nan=False: a NaN counter must fail the write, not persist as
        # an invalid-JSON literal (mode='json' would silently coerce it to
        # null, so dump the python form instead — all fields are JSON-native).
        text = json.dumps(
            checkpoint.model_dump(mode="python"), indent=2, ensure_ascii=False, allow_nan=False
        )
        _atomic_write_text(self.checkpoint_path, text)

    def load_checkpoint(self) -> Checkpoint | None:
        """Load the checkpoint, migrating a version-1 file in memory (the
        migrated form is written by the next save, under the run lock). A v1
        state that cannot be mapped raises CheckpointMigrationError."""
        if not self.checkpoint_path.is_file():
            return None
        text = self.checkpoint_path.read_text(encoding="utf-8")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"checkpoint is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("checkpoint is not a JSON object")
        version = int(data.get("schema_version") or 1)
        if version > SCHEMA_VERSION:
            raise ValueError(
                f"checkpoint schema_version {version} is newer than this build understands "
                f"({SCHEMA_VERSION}) — upgrade before reading or resuming this run"
            )
        if version < SCHEMA_VERSION:
            from research_agent.evidence.migrate import migrate_v1

            return migrate_v1(data, self)
        return Checkpoint.model_validate(data)
