"""B-114 (research template 1.6.0, lesson `full-disk-pauses-and-resumes`): a full disk pauses a job, never fails it for
good. Under the floor a job waits in the queue; a run a full disk stopped is `disk_low` and the service continues it
once space is back, without a person and without paying again for what was recorded."""
from __future__ import annotations

import asyncio
import errno

import pytest

from research_agent.service import runtime as rt_mod
from research_agent.service.runtime import JOB_FLOOR_BYTES, RESUME_MARGIN_BYTES, Runtime, out_of_space
from research_agent.service.store import Store

RESEARCH = {"kind": "research", "runbook": "market-pulse", "inputs": {"market": "eSIM"}}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("PROWL_API_KEY", "p")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    monkeypatch.setattr(rt_mod, "DISK_POLL_SECONDS", 0.01)


def test_enospc_is_found_anywhere_in_the_chain():
    try:
        try:
            raise OSError(errno.ENOSPC, "No space left on device")
        except OSError as inner:
            raise RuntimeError("writing the ledger") from inner
    except RuntimeError as outer:
        assert out_of_space(outer)
    assert not out_of_space(ValueError("x"))


async def test_a_job_waits_in_the_queue_while_the_disk_is_full(tmp_path, env):
    free = {"bytes": JOB_FLOOR_BYTES - 1}
    rt = Runtime(Store(tmp_path), free_bytes=lambda: free["bytes"])
    ran = []

    async def live(job):
        ran.append(job["id"])
        return {"data": []}

    rt.live = live
    job, _ = rt.store.create(RESEARCH, "k1")
    rt.store.decide(job["id"], job["proposal"]["digest"], True)
    task = asyncio.create_task(rt.execute(job["id"]))
    await asyncio.sleep(0.1)
    assert ran == [] and rt.store.job(job["id"])["phase"] == "queued"
    kinds = [e["kind"] for e in rt.store.events(after=0, limit=50)["events"]]
    assert kinds.count("job.disk_wait") == 1
    free["bytes"] = JOB_FLOOR_BYTES * 3
    await asyncio.wait_for(task, 2)
    assert ran == [job["id"]] and rt.store.job(job["id"])["status"] == "completed"


async def test_a_run_stopped_by_a_full_disk_is_disk_low_and_continues_by_itself(tmp_path, env):
    free = {"bytes": JOB_FLOOR_BYTES * 2}
    rt = Runtime(Store(tmp_path), free_bytes=lambda: free["bytes"])

    async def full(job):
        raise RuntimeError("ledger write") from OSError(errno.ENOSPC, "No space left on device")

    rt.live = full
    job, _ = rt.store.create(RESEARCH, "k1")
    rt.store.decide(job["id"], job["proposal"]["digest"], True)
    await rt.execute(job["id"])
    stopped = rt.store.job(job["id"])
    assert stopped["status"] == "failed" and stopped["error"]["code"] == "disk_low"

    started = []

    async def nothing(job_id):
        started.append(job_id)

    rt.execute = nothing
    free["bytes"] = JOB_FLOOR_BYTES + RESUME_MARGIN_BYTES - 1
    assert rt.resume_disk_low() == [], "not a margin above the floor yet"
    free["bytes"] = JOB_FLOOR_BYTES + RESUME_MARGIN_BYTES
    [resume_id] = rt.resume_disk_low()
    resume = rt.store.job(resume_id)
    assert resume["request"]["resumeJobId"] == job["id"] and resume["status"] == "working"
    assert resume["decision"]["by"] in {"service", "allowance"}
    assert rt.resume_disk_low() == [], "one continuation per stopped job"
