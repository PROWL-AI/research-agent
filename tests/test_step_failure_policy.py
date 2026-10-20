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
def deep_runbook(patched_runbooks) -> Path:
    # deep effort: five workers share one refusal count.
    _write_runbook(patched_runbooks, "policy-deep", 60)
    return patched_runbooks


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
            error.stops_run = error_class in self.stops_run or error_class == "insufficient_funds"
            raise error
        return await super().call_tool(name, arguments, idempotency_key)


def _plan(*domains: str, transform_after: int | None = None, optional: set[str] = frozenset()) -> dict:
    steps: list[dict[str, Any]] = []
    for i, domain in enumerate(domains):
        step = {"step": f"s{i}-{domain}", "tool": TOOL, "arguments": {"domain": domain}}
        if domain in optional:
            step["on_error_skip"] = True
        steps.append(step)
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
    assert checkpoint["stop_reason"].count("s0-empty.com") == 1  # named once, with the server's reason
    assert "no results for empty.com" in checkpoint["stop_reason"]


@pytest.mark.parametrize("error_class", ["insufficient_funds"])
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

    assert STOPPING_ERROR_CLASSES == {"insufficient_funds"}
    # forbidden also means one provider's credentials, a denylisted tool or one tool
    # outside the key's scope (prowl-app mcp_server/tools.py): it fails one step.
    assert "forbidden" not in STOPPING_ERROR_CLASSES
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


async def test_forbidden_fails_one_step_and_the_run_goes_on(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    prowl = RefusingProwl({"scoped.com": "forbidden"})
    llm = FakeLLM()
    llm.plan_payload = _plan("scoped.com", "b.com")
    result = await Orchestrator(prowl, llm, runs_root=runs).run("policy-lookup", BRIEF, run_id="forbidden")
    assert [c["arguments"]["domain"] for c in prowl.tool_calls] == ["scoped.com", "b.com"]
    assert result.terminal_code == "step_failed"


async def test_optional_refusals_neither_count_nor_stop(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    bad = [f"opt{i}.com" for i in range(7)]
    prowl = RefusingProwl({d: "not_found" for d in bad})
    llm = FakeLLM()
    llm.plan_payload = _plan(*bad, "good.com", optional=set(bad), transform_after=6)
    result = await Orchestrator(prowl, llm, runs_root=runs).run("policy-lookup", BRIEF, run_id="optional")
    assert len(prowl.tool_calls) == 8  # seven optional refusals in a row stop nothing
    states = [s["state"] for s in _checkpoint(runs, "optional")["steps"]]
    assert states == ["skipped_on_error"] * 7 + ["completed", "completed"]
    assert (result.status, result.terminal_code) == ("complete", "completed")


async def test_the_refusal_cap_is_shared_by_every_worker(deep_runbook, tmp_path):
    # deep effort runs five workers; a provider down for every tool must cost
    # about MAX_REFUSALS_IN_ROW attempts, not five per worker.
    from research_agent.agent.subagent import MAX_REFUSALS_IN_ROW

    runs = tmp_path / "runs"
    bad = [f"down{i}.com" for i in range(30)]
    prowl = RefusingProwl({d: "provider_error" for d in bad})
    llm = FakeLLM()
    llm.plan_payload = _plan(*bad)
    result = await Orchestrator(prowl, llm, runs_root=runs).run("policy-deep", BRIEF, run_id="shared")
    assert MAX_REFUSALS_IN_ROW <= len(prowl.tool_calls) < 2 * MAX_REFUSALS_IN_ROW
    assert result.terminal_code == "step_failed"


async def test_a_budget_stop_after_a_refusal_keeps_its_code_and_names_the_refusal(patched_runbooks, tmp_path):
    # mini-teardown: max_tool_calls=2
    runs = tmp_path / "runs"
    prowl = RefusingProwl({"empty.com": "not_found"})
    llm = FakeLLM()
    llm.plan_payload = _plan("empty.com", "b.com", "c.com")
    result = await Orchestrator(prowl, llm, runs_root=runs).run("mini-teardown", BRIEF, run_id="budget")
    checkpoint = _checkpoint(runs, "budget")
    assert result.terminal_code == "budget_tools"
    assert checkpoint["stop_reason"].startswith("max_tool_calls=")
    assert "s0-empty.com" in checkpoint["stop_reason"]


async def test_a_failed_optional_step_after_a_stopping_refusal_runs_again_on_resume(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    prowl = RefusingProwl({"a.com": "insufficient_funds"})
    llm = FakeLLM()
    llm.plan_payload = _plan("a.com", "b.com", optional={"a.com"})
    await Orchestrator(prowl, llm, runs_root=runs).run("policy-lookup", BRIEF, run_id="topup")
    assert [s["state"] for s in _checkpoint(runs, "topup")["steps"]] == ["failed", "pending"]

    resumed = await Orchestrator(RefusingProwl({}), llm, runs_root=runs).run("policy-lookup", BRIEF, run_id="topup")
    steps = _checkpoint(runs, "topup")["steps"]
    assert [(s["state"], s["reason"]) for s in steps] == [("completed", None), ("completed", None)]
    assert resumed.status == "complete"


async def test_the_writer_is_told_which_steps_were_refused_and_why(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    prowl = RefusingProwl({"empty.com": "unknown_error"})
    llm = FakeLLM()
    llm.plan_payload = _plan("empty.com", "b.com")
    await Orchestrator(prowl, llm, runs_root=runs).run("policy-lookup", BRIEF, run_id="writer")
    writer = [m for call in llm.calls for m in call["messages"] if m["role"] == "system" and "PARTIAL RUN" in m["content"]]
    assert writer, "the writer got no partial note"
    note = writer[-1]["content"]
    assert "refused by the data source" in note and "no results for empty.com" in note
    assert "stopped before completing every planned step" not in note


async def test_a_transform_is_told_which_steps_before_it_were_refused(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    prowl = RefusingProwl({"quote.com": "not_found"})
    llm = FakeLLM()
    llm.plan_payload = _plan("b.com", "quote.com", transform_after=1)
    await Orchestrator(prowl, llm, runs_root=runs).run("policy-lookup", BRIEF, run_id="transform")
    transform = [m["content"] for call in llm.calls for m in call["messages"]
                 if m["role"] == "user" and m["content"].startswith("## Instruction")]
    assert transform and "returned no data" in transform[-1] and "s1-quote.com" in transform[-1]


async def test_an_llm_budget_stop_after_a_refusal_still_names_the_llm_budget(lookup_runbook, tmp_path, monkeypatch):
    from research_agent.agent import orchestrator as orch_module
    from research_agent.llm import LLMBudgetExceeded

    async def refused_writer(*args, **kwargs):
        raise LLMBudgetExceeded("max_llm_usd=1.0 leaves no room for the writer", stage="writer")

    monkeypatch.setattr(orch_module, "produce_report", refused_writer)
    runs = tmp_path / "runs"
    prowl = RefusingProwl({"empty.com": "not_found"})
    llm = FakeLLM()
    llm.plan_payload = _plan("empty.com", "b.com")
    await Orchestrator(prowl, llm, runs_root=runs).run("policy-lookup", BRIEF, run_id="llmcap")
    report = (runs / "llmcap" / "report.md").read_text()
    assert "max_llm_usd=" in report and "s0-empty.com" in report
