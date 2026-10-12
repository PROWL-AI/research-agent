"""Crash injection at every durable boundary of a run (wave 2, KA-05/KA-10/KA-12).

A clean run of one data step and one transform performs N persistence writes
(checkpoint, raw, ledger). For every n in 1..N the run is killed at the n-th
write — by a BaseException, which, like a process death, escapes every
`except Exception` and skips the owner's terminal write — then resumed by a
fresh process. Each resume must:

(a) never report a step completed without its raw artifact on disk;
(b) never dispatch again a step whose raw was already saved;
(c) never lose recorded spend (spend after resume >= spend on disk at the crash);
(d) finish `complete`.
"""

from __future__ import annotations

import pytest

from research_agent.agent.orchestrator import Orchestrator
from research_agent.evidence.ledger import Ledger
from research_agent.evidence.store import ArtifactStore

from conftest import FakeLLM, FakeProwl

BRIEF = {"competitors": ["example.com"]}
PLAN = {"plan": [
    {"step": "baseline", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "a.example.com"}},
    {"step": "synthesize", "tool": "transform", "instruction": "summarize the baseline"},
]}


class ProcessDeath(BaseException):
    """Not an Exception: nothing in the run may catch it, as with a kill -9."""


class CrashAt:
    def __init__(self, monkeypatch, n: int) -> None:
        self.n, self.count = n, 0
        for owner, name in ((ArtifactStore, "save_checkpoint"), (ArtifactStore, "_write_artifact"),
                            (Ledger, "save")):
            original = getattr(owner, name)
            monkeypatch.setattr(owner, name, self._wrap(original))

    def _wrap(self, original):
        def wrapped(*args, **kwargs):
            self.count += 1
            if self.count == self.n:
                raise ProcessDeath(f"killed at write {self.n}")
            return original(*args, **kwargs)
        return wrapped


def _llm() -> FakeLLM:
    llm = FakeLLM()
    llm.plan_payload = PLAN
    llm.claims_payload = {"claims": [{"claim": "Visits 1200", "value": 1200, "unit": "visits",
                                      "subject": "a.example.com visits"}]}
    return llm


async def _count_writes(tmp_path, monkeypatch) -> int:
    with monkeypatch.context() as m:
        counter = CrashAt(m, n=10**9)
        result = await Orchestrator(FakeProwl(), _llm(), runs_root=tmp_path / "clean").run(
            "mini-teardown", BRIEF, run_id="clean")
        assert result.status == "complete"
        return counter.count


async def test_every_durable_boundary_is_resumable_without_paying_twice(
    patched_runbooks, tmp_path, monkeypatch
):
    monkeypatch.setenv("RESEARCH_NO_SUBAGENTS", "1")
    total = await _count_writes(tmp_path, monkeypatch)
    assert total >= 8, total  # the run really has many boundaries to cut
    for n in range(1, total + 1):
        runs = tmp_path / f"crash-{n}"
        with monkeypatch.context() as m:
            CrashAt(m, n)
            with pytest.raises(ProcessDeath):
                await Orchestrator(FakeProwl(), _llm(), runs_root=runs).run("mini-teardown", BRIEF, run_id="r")
        store = ArtifactStore(runs / "r")
        before = store.load_checkpoint()
        if before is None:
            continue  # died before the run existed: nothing to resume
        saved = {s.step_id for s in before.steps if s.state in ("raw_saved", "completed") and s.kind == "data"}
        for s in before.steps:  # (a)
            if s.state == "completed":
                assert s.raw_ref and store.resolve(s.raw_ref).is_file(), (n, s)
        spend_before = before.spend_usd("tool")

        prowl = FakeProwl()
        result = await Orchestrator(prowl, _llm(), runs_root=runs).run("mini-teardown", BRIEF, run_id="r")
        after = store.load_checkpoint()
        dispatched = {key.split(":")[1] for key in (c["idempotency_key"] for c in prowl.tool_calls)}
        assert not (dispatched & saved), (n, dispatched, saved)  # (b)
        assert after.spend_usd("tool") >= spend_before, n  # (c) never lost
        # (c) never double counted: one logical attempt per data step, also when
        # an outcome_unknown call was re-sent with its key.
        data_ids = [s.step_id for s in after.steps if s.kind == "data"]
        assert all(sum(a.step_id == sid for a in after.attempts) == 1 for sid in data_ids), n
        assert result.status == "complete", (n, result.terminal_code, after.step_counts())  # (d)
        ledger = Ledger.load(runs / "r" / "ledger.json")
        assert len(ledger.claims) == 2, (n, [c.claim for c in ledger.claims])  # replaced, not duplicated
