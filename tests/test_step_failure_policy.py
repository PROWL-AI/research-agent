"""B-049: one refused step is evidence of absence, not the end of the run.

Live run accept-finance-20261018b executed 3 of 44 steps: its first required step
was answered «no results» and the worker, and every later segment, stopped. A
refusal that will repeat for every call (an empty wallet, a forbidden key, the
service's own limit) or an unknown outcome still stops; one empty answer does not.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from research_agent.agent.orchestrator import Orchestrator
from research_agent.prowl_client import ToolCallError

from conftest import FakeLLM, FakeProwl
from test_subagents import _write_runbook

TOOL = "spyfu_get_domain_stats"
BRIEF = {"competitors": ["a.com"]}


@pytest.fixture
def lookup_runbook(patched_runbooks) -> Path:
    # lookup effort: one worker, so "the worker takes its next step" is observable.
    _write_runbook(patched_runbooks, "policy-lookup", 60, effort="lookup")
    return patched_runbooks


class RefusingProwl(FakeProwl):
    """Refuses calls by their `domain` argument, the way the client raises them."""

    def __init__(self, refuse: dict[str, str], stops_run: set[str] = frozenset()) -> None:
        super().__init__()
        self.refuse = refuse  # domain -> error_class
        self.stops_run = set(stops_run)

    async def call_tool(self, name: str, arguments: dict[str, Any], idempotency_key: str | None = None) -> Any:
        domain = arguments.get("domain")
        if domain in self.refuse:
            self.tool_calls.append({"name": name, "arguments": arguments, "idempotency_key": idempotency_key})
            self.call_log.append(object())
            error_class = self.refuse[domain]
            error = ToolCallError(f"prowl_call_tool: {error_class}: no results for {domain}")
            error.error_class = error_class
            error.stops_run = error_class in self.stops_run or error_class in ("insufficient_funds", "forbidden")
            raise error
        return await super().call_tool(name, arguments, idempotency_key)


def _plan(*domains: str, transform_after: int | None = None) -> dict:
    steps: list[dict[str, Any]] = []
    for i, domain in enumerate(domains):
        steps.append({"step": f"s{i}-{domain}", "tool": TOOL, "arguments": {"domain": domain}})
        if transform_after is not None and i == transform_after:
            steps.append({"step": "synthesis", "tool": "transform", "arguments": {}, "instruction": "sum up"})
    return {"plan": steps}


def _checkpoint(runs: Path, run_id: str) -> dict:
    return json.loads((runs / run_id / "checkpoint.json").read_text())


async def test_a_refused_required_step_does_not_stop_the_run(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    prowl = RefusingProwl({"empty.com": "unknown_error"})
    llm = FakeLLM()
    llm.plan_payload = _plan("empty.com", "b.com", "c.com", "d.com", transform_after=1)
    result = await Orchestrator(prowl, llm, runs_root=runs).run("policy-lookup", BRIEF, run_id="refused")

    called = [c["arguments"]["domain"] for c in prowl.tool_calls]
    assert called == ["empty.com", "b.com", "c.com", "d.com"]  # the worker went on, the later segment ran
    checkpoint = _checkpoint(runs, "refused")
    states = {s["step"]: s["state"] for s in checkpoint["steps"]}
    assert states["s0-empty.com"] == "failed"
    assert "no results for empty.com" in next(s["reason"] for s in checkpoint["steps"] if s["step"] == "s0-empty.com")
    assert [states[k] for k in ("s1-b.com", "synthesis", "s2-c.com", "s3-d.com")] == ["completed"] * 4
    # D4: partial, step_failed, and the failed step named before the writer ran
    assert (result.status, result.terminal_code) == ("partial", "step_failed")
    assert "s0-empty.com" in checkpoint["stop_reason"]


@pytest.mark.parametrize("error_class", ["insufficient_funds", "forbidden"])
async def test_a_refusal_that_repeats_for_every_call_still_stops_the_run(lookup_runbook, tmp_path, error_class):
    runs = tmp_path / "runs"
    prowl = RefusingProwl({"a.com": error_class})
    llm = FakeLLM()
    llm.plan_payload = _plan("a.com", "b.com", "c.com", transform_after=0)
    result = await Orchestrator(prowl, llm, runs_root=runs).run("policy-lookup", BRIEF, run_id=f"stop-{error_class}")

    assert [c["arguments"]["domain"] for c in prowl.tool_calls] == ["a.com"]
    states = [s["state"] for s in _checkpoint(runs, f"stop-{error_class}")["steps"]]
    assert states[0] == "failed" and set(states[1:]) == {"pending"}
    assert (result.status, result.terminal_code) == ("partial", "step_failed")


async def test_a_service_local_refusal_still_stops_the_run(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    prowl = RefusingProwl({"a.com": "local_limit"}, stops_run={"local_limit"})
    llm = FakeLLM()
    llm.plan_payload = _plan("a.com", "b.com")
    await Orchestrator(prowl, llm, runs_root=runs).run("policy-lookup", BRIEF, run_id="local")
    assert [c["arguments"]["domain"] for c in prowl.tool_calls] == ["a.com"]


def test_the_service_marks_its_local_refusals_as_stopping():
    import inspect

    from research_agent.service import runtime

    source = inspect.getsource(runtime)
    # both local refusals (call limit, journal unavailable) say nothing was sent and repeat
    assert source.count("stops_run = True") >= 2


def test_the_client_marks_a_wallet_or_key_refusal_as_stopping():
    from research_agent.prowl_client import STOPPING_ERROR_CLASSES

    assert {"insufficient_funds", "forbidden"} <= STOPPING_ERROR_CLASSES
    assert "not_found" not in STOPPING_ERROR_CLASSES and "unknown_error" not in STOPPING_ERROR_CLASSES
    assert ToolCallError("x").stops_run is False


async def test_five_refusals_in_a_row_stop_the_worker(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    bad = [f"bad{i}.com" for i in range(6)]
    prowl = RefusingProwl({d: "provider_error" for d in bad})
    llm = FakeLLM()
    llm.plan_payload = _plan(*bad, "good.com")
    result = await Orchestrator(prowl, llm, runs_root=runs).run("policy-lookup", BRIEF, run_id="cascade")

    assert len(prowl.tool_calls) == 5  # the fifth refusal in a row stops; the rest stay pending
    checkpoint = _checkpoint(runs, "cascade")
    assert [s["state"] for s in checkpoint["steps"]][-2:] == ["pending", "pending"]
    assert "in a row" in checkpoint["stop_reason"]
    assert result.terminal_code == "step_failed"


async def test_a_success_between_refusals_resets_the_cascade_count(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    bad = [f"bad{i}.com" for i in range(8)]
    domains = bad[:4] + ["good.com"] + bad[4:]
    prowl = RefusingProwl({d: "not_found" for d in bad})
    llm = FakeLLM()
    llm.plan_payload = _plan(*domains)
    await Orchestrator(prowl, llm, runs_root=runs).run("policy-lookup", BRIEF, run_id="reset")
    assert len(prowl.tool_calls) == 9  # 4 refused, 1 ok, 4 refused: never five in a row


async def test_resume_after_a_refused_step_runs_only_that_step(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    prowl = RefusingProwl({"empty.com": "unknown_error"})
    llm = FakeLLM()
    llm.plan_payload = _plan("empty.com", "b.com")
    await Orchestrator(prowl, llm, runs_root=runs).run("policy-lookup", BRIEF, run_id="resume")

    again = RefusingProwl({})
    resumed = await Orchestrator(again, llm, runs_root=runs).run("policy-lookup", BRIEF, run_id="resume")
    assert [c["arguments"]["domain"] for c in again.tool_calls] == ["empty.com"]  # b.com is never paid twice
    assert (resumed.status, resumed.terminal_code) == ("complete", "completed")
