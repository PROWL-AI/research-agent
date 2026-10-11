"""The run lock: the one owner of "who may write this run's lifecycle state".

A run dir is written by exactly one process at a time — the one holding the
advisory flock on `<run_dir>/.lock`. The live owner is `Orchestrator.run`;
every writer outside a live run (startup/CLI/service reconciliation,
`rewrite_report`, `prune`) takes the lock non-blocking first and writes nothing
when it is held elsewhere. Two processes sharing one runs root (a CLI and an
MCP server, two servers, the Fabric service) must never execute or rewrite the
same run: counters go last-writer-wins, claim ids duplicate and calls bill
twice.

flock locks belong to an open file description, so a second `RunLock` on the
same run dir is refused even inside the same process.
"""

from __future__ import annotations

import fcntl
import logging
import os
from pathlib import Path

from research_agent.events import emit
from research_agent.evidence import terminal
from research_agent.evidence.store import ArtifactStore

log = logging.getLogger(__name__)

LOCK_NAME = ".lock"

#: stop_reason written when reconciliation claims an orphaned 'running' run.
ORPHAN_STOP_REASON = "process exited before completion"


class RunLocked(RuntimeError):
    """The run's lock is held by another owner."""


class RunLock:
    def __init__(self, run_dir: Path | str) -> None:
        self.run_dir = Path(run_dir)
        self.path = self.run_dir / LOCK_NAME
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self, blocking: bool = False) -> bool:
        """Take the lock; False when another owner holds it (non-blocking).

        Never pass blocking=True from event-loop code: flock would block the
        loop."""
        if self._fd is not None:
            return True
        self.run_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is not None:
            fd, self._fd = self._fd, None
            os.close(fd)  # closing the descriptor releases the flock

    def detach(self) -> int:
        """Hand the held descriptor to the caller (who closes it to release)."""
        if self._fd is None:
            raise RuntimeError("lock not held")
        fd, self._fd = self._fd, None
        return fd

    def __enter__(self) -> "RunLock":
        if not self.acquire(blocking=False):
            raise RunLocked(f"run {self.run_dir.name} is locked by another process")
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def is_locked_elsewhere(run_dir: Path | str) -> bool:
    """True when some other owner holds the run's lock. A probe: it takes the
    lock non-blocking and releases it at once, and never creates a lock file
    (no lock file means nobody can hold it)."""
    path = Path(run_dir) / LOCK_NAME
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


#: The canvas (docs/specs/2026-10-11-waves-canvas.md §2 N-OWN) names the probe
#: this way; both names are the same function.
is_held_elsewhere = is_locked_elsewhere


def reconcile_orphans(runs_root: Path | str) -> list[str]:
    """Mark every orphaned 'running' checkpoint under runs_root as interrupted.

    A checkpoint is orphaned only when its lock is free: a held lock means a
    live owner (in this or another process) and the run is skipped. The
    checkpoint is re-read under the lock — the owner may have written its
    terminal state between the first read and the acquire. A corrupt
    checkpoint is logged and skipped: one bad run dir must not stop a server
    from starting. 'interrupted' stays resumable. Returns the run ids marked.
    """
    root = Path(runs_root)
    if not root.is_dir():
        return []
    marked: list[str] = []
    for run_dir in sorted(root.iterdir()):
        if not run_dir.is_dir():
            continue
        store = ArtifactStore(run_dir)
        try:
            checkpoint = store.load_checkpoint()
        except (ValueError, OSError) as exc:
            log.error("run dir %s has a corrupt checkpoint, skipping: %s", run_dir.name, exc)
            continue
        if checkpoint is None or checkpoint.status != "running":
            continue
        lock = RunLock(run_dir)
        if not lock.acquire(blocking=False):
            emit(log, "run.reconcile.skipped_active", run_id=checkpoint.run_id)
            continue
        try:
            try:
                checkpoint = store.load_checkpoint()
            except (ValueError, OSError) as exc:
                log.error("run dir %s has a corrupt checkpoint, skipping: %s", run_dir.name, exc)
                continue
            if checkpoint is None or checkpoint.status != "running":
                continue
            checkpoint.status = "interrupted"
            checkpoint.partial = True
            checkpoint.stop_reason = ORPHAN_STOP_REASON
            checkpoint.terminal_code = terminal.INTERRUPTED
            store.save_checkpoint(checkpoint)
            emit(
                log, "run.reconcile.interrupted", logging.WARNING,
                run_id=checkpoint.run_id, status=checkpoint.status,
                terminal_code=checkpoint.terminal_code, partial=checkpoint.partial,
            )
            marked.append(checkpoint.run_id)
        finally:
            lock.release()
    return marked
