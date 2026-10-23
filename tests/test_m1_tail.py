"""M1 tail rows (B-082, B-085, B-086): the closing pass on the milestone's own findings."""

from __future__ import annotations

import json

import pytest

from research_agent.agent import tool_limits
from research_agent.agent.orchestrator import Orchestrator
from research_agent.evidence.store import ArtifactStore

from conftest import FakeLLM, FakeProwl
from test_ka_contracts import _v1_run


@pytest.fixture
def limited_spyfu(monkeypatch):
    """A measured limit on the test runbook's tool: only the upper-case spelling of a.com,
    so a judged step would be rewritten ('a.com' -> 'A.COM') or refused (any other value)."""
    limit = tool_limits.ArgumentLimit(allowed=frozenset({"A.COM"}), note="test", source="test")
    monkeypatch.setitem(tool_limits.LIMITS, "spyfu_get_domain_stats", {"domain": limit})


@pytest.mark.parametrize("domain", ["a.com", "b.com"])
async def test_a_v1_step_resent_under_its_legacy_key_goes_out_as_v1_sent_it(patched_runbooks, tmp_path, limited_spyfu, domain):
    """B-082: the v1 key may already have reached the server with these params; a new
    spelling (canonical) or a refusal by a rule learned since must not apply to it."""
    plan = [{"step": "s0", "tool": "spyfu_get_domain_stats", "arguments": {"domain": domain}}]
    _v1_run(tmp_path / "legacy", plan=plan, completed=[], raw_for=[], skipped=[
        {"index": 0, "step": "s0", "tool": "spyfu_get_domain_stats", "reason": "step 's0' failed: reset",
         "kind": "runtime_skip"}])
    prowl = FakeProwl()
    await Orchestrator(prowl, FakeLLM(), tmp_path).run("mini-teardown", {}, run_id="legacy")
    assert [c["arguments"] for c in prowl.tool_calls] == [{"domain": domain}]
    assert prowl.tool_calls[0]["idempotency_key"] == "legacy:0:spyfu_get_domain_stats"
    step = ArtifactStore(tmp_path / "legacy").load_checkpoint().steps[0]
    assert step.state == "completed"


async def test_several_output_references_share_one_cap_per_step(tmp_path, patched_runbooks):
    """B-085: three references to a 20 000-character page were 3 x 16 000 characters in one argument."""
    from research_agent.agent import bindings
    from test_subagents import _write_runbook

    class BigProwl(FakeProwl):
        async def call_tool(self, name, arguments, idempotency_key=None):
            self.tool_calls.append({"name": name, "arguments": arguments, "idempotency_key": idempotency_key})
            self.call_log.append(object())
            return {"markdown": "x" * 20_000}

    _write_runbook(patched_runbooks, "tail-lookup", 60, effort="lookup")
    llm = FakeLLM()
    llm.plan_payload = {"plan": [
        {"step": "p1", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "a.com"}},
        {"step": "p2", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "b.com"}},
        {"step": "p3", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "c.com"}},
        {"step": "all", "tool": "spyfu_get_domain_stats",
         "arguments": {"domain": "{{output:p1}} {{output:p2}} {{output:p3}}"}},
    ]}
    prowl = BigProwl()
    await Orchestrator(prowl, llm, runs_root=tmp_path / "runs").run("tail-lookup", {"competitors": ["a.com"]}, run_id="caps")
    sent = prowl.tool_calls[-1]["arguments"]["domain"]
    assert len(sent) < bindings.OUTPUT_CAP + 200 and sent.count("more characters]") == 3


@pytest.mark.parametrize("workers", [1, 3])
async def test_a_forwarding_step_keeps_its_call_under_a_tool_budget(tmp_path, patched_runbooks, workers):
    """B-086: the analysis ran after every unrelated step, so a tool budget left it unsent."""
    from test_subagents import _write_runbook

    _write_runbook(patched_runbooks, "tail-budget", 4, effort="lookup")
    llm = FakeLLM()
    llm.plan_payload = {"plan": [
        {"step": "s0", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "c0.com"}},
        {"step": "scrape page", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "a.com"}},
        {"step": "analyse", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "A: {{output:scrape_page}}"}},
        {"step": "s3", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "c3.com"}},
        {"step": "s4", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "c4.com"}},
        {"step": "s5", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "c5.com"}},
    ]}
    prowl = FakeProwl()
    result = await Orchestrator(prowl, llm, runs_root=tmp_path / "runs", max_workers=workers).run(
        "tail-budget", {"competitors": ["a.com"]}, run_id=f"b{workers}")
    checkpoint = json.loads((tmp_path / "runs" / f"b{workers}" / "checkpoint.json").read_text())
    states = {s["step"]: s["state"] for s in checkpoint["steps"]}
    assert states["analyse"] == "completed" and states["scrape page"] == "completed"
    assert len(prowl.tool_calls) <= 4
    assert (result.status, result.terminal_code) == ("partial", "budget_tools")
    assert "skipped_budget" in states.values()


# ── seam round 1 on the tail ───────────────────────────────────────────────


@pytest.mark.parametrize("workers", [1, 3])
async def test_the_reserve_never_skips_the_producer_of_a_later_level(tmp_path, patched_runbooks, workers, caplog):
    from test_subagents import _write_runbook

    _write_runbook(patched_runbooks, "tail-producer", 4, effort="lookup")
    llm = FakeLLM()
    llm.plan_payload = {"plan": [
        {"step": "s0", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "c0.com"}},
        {"step": "s3", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "c3.com"}},
        {"step": "s4", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "c4.com"}},
        {"step": "scrape page", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "a.com"}},
        {"step": "analyse", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "A: {{output:scrape_page}}"}},
    ]}
    prowl = FakeProwl()
    with caplog.at_level("WARNING"):
        result = await Orchestrator(prowl, llm, runs_root=tmp_path / "runs", max_workers=workers).run(
            "tail-producer", {"competitors": ["a.com"]}, run_id=f"p{workers}")
    states = {s["step"]: s["state"] for s in json.loads((tmp_path / "runs" / f"p{workers}" / "checkpoint.json").read_text())["steps"]}
    assert states["scrape page"] == "completed" and states["analyse"] == "completed"
    assert len(prowl.tool_calls) == 4 and result.terminal_code == "budget_tools"
    assert "event=budget.stop" in caplog.text


async def test_the_reserve_never_skips_a_step_whose_outcome_is_unknown(tmp_path, patched_runbooks):
    """Its next send must reuse its key: skipping it would mint a new one and could bill twice."""
    from research_agent.evidence.store import AttemptRecord, Checkpoint, StepRecord, make_step_id
    from test_subagents import _write_runbook

    _write_runbook(patched_runbooks, "tail-unknown", 2, effort="lookup")
    tool = "spyfu_get_domain_stats"
    steps = [StepRecord(step_id=make_step_id(i, tool, a), raw_index=i, tool=tool, step=n, arguments=a)
             for i, (n, a) in enumerate([("u", {"domain": "u.com"}), ("p", {"domain": "p.com"}),
                                         ("f", {"domain": "F: {{output:p}}"})])]
    steps[0].state = "outcome_unknown"
    attempt = AttemptRecord(attempt_id=steps[0].step_id + "#1", step_id=steps[0].step_id, kind="tool", attempt_no=1,
                            idempotency_key=f"r:{steps[0].step_id}:1", outcome="unknown")
    steps[0].attempt_ids = [attempt.attempt_id]
    store = ArtifactStore(tmp_path / "runs" / "r")
    store.save_checkpoint(Checkpoint(run_id="r", runbook="tail-unknown", status="interrupted",
                                     brief={"competitors": ["a.com"]}, steps=steps, attempts=[attempt]))
    prowl = FakeProwl()
    await Orchestrator(prowl, FakeLLM(), runs_root=tmp_path / "runs", max_workers=1).run("tail-unknown", {}, run_id="r")
    keys = [c["idempotency_key"] for c in prowl.tool_calls]
    assert f"r:{steps[0].step_id}:1" in keys
    assert not any(k == f"r:{steps[0].step_id}:2" for k in keys)


def test_one_reference_written_twice_still_shares_one_cap():
    from research_agent.agent import bindings
    assert bindings.output_ref_count({"q": "{{output:p}} vs {{output:p}}", "r": ["{{output:q}}"]}) == 3


# ── seam round 2 on the tail: calls a reserve kept but nobody used go back ─


def _producer_plan():
    return {"plan": [
        {"step": "s0", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "c0.com"}},
        {"step": "s3", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "c3.com"}},
        {"step": "s4", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "c4.com"}},
        {"step": "scrape page", "tool": "dataforseo_bl_summary", "arguments": {"target": "a.com"}},
        {"step": "analyse", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "A: {{output:scrape_page}}"}},
    ]}


async def _run_producer_case(tmp_path, patched_runbooks, prowl, run_id, workers):
    from test_subagents import _write_runbook

    _write_runbook(patched_runbooks, "tail-give-back", 4, effort="lookup")
    llm = FakeLLM()
    llm.plan_payload = _producer_plan()
    result = await Orchestrator(prowl, llm, runs_root=tmp_path / "runs", max_workers=workers).run(
        "tail-give-back", {"competitors": ["a.com"]}, run_id=run_id)
    states = {s["step"]: s["state"] for s in json.loads((tmp_path / "runs" / run_id / "checkpoint.json").read_text())["steps"]}
    return result, states


@pytest.mark.parametrize("workers", [1, 3])
async def test_a_call_kept_for_a_refused_producer_goes_back(tmp_path, patched_runbooks, workers):
    prowl = FakeProwl()
    prowl.fail_on.add("dataforseo_bl_summary")
    result, states = await _run_producer_case(tmp_path, patched_runbooks, prowl, f"refused{workers}", workers)
    assert states["s4"] == "completed" and len(prowl.tool_calls) == 4


@pytest.mark.parametrize("workers", [1, 3])
async def test_a_call_kept_for_an_unsent_producer_goes_back_and_the_run_names_the_real_cause(
        tmp_path, patched_runbooks, workers, monkeypatch):
    limit = tool_limits.ArgumentLimit(allowed=frozenset({"x.com"}), note="test", source="test")
    monkeypatch.setitem(tool_limits.LIMITS, "dataforseo_bl_summary", {"target": limit})
    prowl = FakeProwl()
    result, states = await _run_producer_case(tmp_path, patched_runbooks, prowl, f"unsent{workers}", workers)
    assert states["s4"] == "completed" and states["scrape page"] == "failed"
    assert result.terminal_code != "budget_tools"


async def test_a_reference_written_twice_shares_the_cap_through_the_dispatch(tmp_path, patched_runbooks):
    from research_agent.agent import bindings
    from test_subagents import _write_runbook

    class BigProwl(FakeProwl):
        async def call_tool(self, name, arguments, idempotency_key=None):
            self.tool_calls.append({"name": name, "arguments": arguments, "idempotency_key": idempotency_key})
            self.call_log.append(object())
            return {"markdown": "x" * 20_000}

    _write_runbook(patched_runbooks, "tail-twice", 60, effort="lookup")
    llm = FakeLLM()
    llm.plan_payload = {"plan": [
        {"step": "p1", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "a.com"}},
        {"step": "twice", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "{{output:p1}} vs {{output:p1}}"}},
    ]}
    prowl = BigProwl()
    await Orchestrator(prowl, llm, runs_root=tmp_path / "runs").run("tail-twice", {"competitors": ["a.com"]}, run_id="twice")
    sent = prowl.tool_calls[-1]["arguments"]["domain"]
    assert len(sent) < bindings.OUTPUT_CAP + 200


# ── B-087: yield only when the calls left can still finish a forward ───────


@pytest.mark.parametrize("workers", [1, 3])
async def test_no_yield_when_the_calls_left_cannot_reach_a_consumer(tmp_path, patched_runbooks, workers):
    """One call left, a pending producer and its consumer: yielding would buy the producer's data
    for the unrelated step's (the consumer never runs), so plan order stands."""
    from test_subagents import _write_runbook

    _write_runbook(patched_runbooks, "tail-cover", 1, effort="lookup")
    llm = FakeLLM()
    llm.plan_payload = {"plan": [
        {"step": "s0", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "c0.com"}},
        {"step": "scrape page", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "a.com"}},
        {"step": "analyse", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "A: {{output:scrape_page}}"}},
    ]}
    prowl = FakeProwl()
    result = await Orchestrator(prowl, llm, runs_root=tmp_path / "runs", max_workers=workers).run(
        "tail-cover", {"competitors": ["a.com"]}, run_id=f"c{workers}")
    states = {s["step"]: s["state"] for s in json.loads((tmp_path / "runs" / f"c{workers}" / "checkpoint.json").read_text())["steps"]}
    assert states["s0"] == "completed"
    assert states["scrape page"] == "skipped_budget" and states["analyse"] != "completed"  # left for a resume
    assert len(prowl.tool_calls) == 1 and result.terminal_code == "budget_tools"


@pytest.mark.parametrize("workers", [1, 3])
async def test_a_yield_still_buys_one_whole_forward_when_the_reserve_is_short(tmp_path, patched_runbooks, workers):
    """One producer read by two consumers, two calls left: the reserve (three) is short, but the
    producer and one consumer still fit, so the unrelated step yields."""
    from test_subagents import _write_runbook

    _write_runbook(patched_runbooks, "tail-short", 2, effort="lookup")
    llm = FakeLLM()
    llm.plan_payload = {"plan": [
        {"step": "s0", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "c0.com"}},
        {"step": "scrape page", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "a.com"}},
        {"step": "analyse", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "A: {{output:scrape_page}}"}},
        {"step": "compare", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "B: {{output:scrape_page}}"}},
    ]}
    prowl = FakeProwl()
    await Orchestrator(prowl, llm, runs_root=tmp_path / "runs", max_workers=workers).run(
        "tail-short", {"competitors": ["a.com"]}, run_id=f"s{workers}")
    states = {s["step"]: s["state"] for s in json.loads((tmp_path / "runs" / f"s{workers}" / "checkpoint.json").read_text())["steps"]}
    assert states["scrape page"] == "completed"
    assert "completed" in (states["analyse"], states["compare"])
    assert states["s0"] == "skipped_budget" and len(prowl.tool_calls) == 2


@pytest.mark.parametrize("workers", [1, 3])
async def test_a_producer_that_will_not_be_sent_takes_no_call_from_the_reserve(tmp_path, patched_runbooks, workers):
    """Seam reading of B-087: p2 holds an unresolved name, so it is never sent; counting it would
    deny x's yield and lose the forward p1 -> c1 that B-086 delivered, and hide p2's real cause."""
    from test_subagents import _write_runbook

    _write_runbook(patched_runbooks, "tail-unsent", 2, effort="lookup")
    llm = FakeLLM()
    llm.plan_payload = {"plan": [
        {"step": "x", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "x.com"}},
        {"step": "p1", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "p1.com"}},
        {"step": "p2", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "{{nobody_resolves_this}}"}},
        {"step": "c1", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "A: {{output:p1}}"}},
        {"step": "c2", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "B: {{output:p2}}"}},
    ]}
    prowl = FakeProwl()
    await Orchestrator(prowl, llm, runs_root=tmp_path / "runs", max_workers=workers).run(
        "tail-unsent", {"competitors": ["a.com"]}, run_id=f"u{workers}")
    steps = {s["step"]: s for s in json.loads((tmp_path / "runs" / f"u{workers}" / "checkpoint.json").read_text())["steps"]}
    assert steps["p1"]["state"] == "completed" and steps["c1"]["state"] == "completed"
    assert steps["x"]["state"] == "skipped_budget"
    assert steps["p2"]["state"] == "failed" and "not sent" in (steps["p2"].get("error") or steps["p2"].get("note") or json.dumps(steps["p2"]))
    assert len(prowl.tool_calls) == 2


# ── B-089 and B-090: the reserve check's cost, reach and stop ──────────────


async def test_the_reserve_check_judges_no_producer_above_its_window(tmp_path, patched_runbooks, monkeypatch):
    """B-089: with calls to spare, no yield is possible, so no producer is judged (each judgement
    reads the artifacts the producer forwards): one judgement per dispatch, no more."""
    from research_agent.agent import subagent
    from test_subagents import _write_runbook

    calls = []
    real = subagent._send_judgement
    monkeypatch.setattr(subagent, "_send_judgement", lambda ctx, cp, rec: calls.append(rec.step) or real(ctx, cp, rec))
    _write_runbook(patched_runbooks, "tail-window", 10, effort="lookup")
    llm = FakeLLM()
    llm.plan_payload = {"plan": [
        {"step": "x1", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "x1.com"}},
        {"step": "x2", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "x2.com"}},
        {"step": "p", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "p.com"}},
        {"step": "c", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "C: {{output:p}}"}},
    ]}
    prowl = FakeProwl()
    await Orchestrator(prowl, llm, runs_root=tmp_path / "runs").run("tail-window", {"competitors": ["a.com"]}, run_id="w")
    assert len(prowl.tool_calls) == 4 and sorted(calls) == ["c", "p", "x1", "x2"]


def test_a_failing_producer_judgement_counts_as_sent(monkeypatch):
    """B-089: one producer's unreadable artifact stays its own failure, never an unrelated step's."""
    from research_agent.agent import subagent

    def boom(*_):
        raise RuntimeError("unreadable raw")

    monkeypatch.setattr(subagent, "_send_judgement", boom)
    assert subagent._will_be_sent(None, None, None) is True


async def test_no_step_yields_once_another_worker_stopped_the_run(tmp_path, patched_runbooks):
    """B-090: after a hard failure the lead runs no later level, so a call kept for one is lost data."""
    from test_subagents import _write_runbook

    _write_runbook(patched_runbooks, "tail-stopped", 3, effort="lookup")
    llm = FakeLLM()
    llm.plan_payload = {"plan": [
        {"step": "h", "tool": "dataforseo_bl_summary", "arguments": {"target": "h.com"}},
        {"step": "p", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "p.com"}},
        {"step": "x1", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "x1.com"}},
        {"step": "x2", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "x2.com"}},
        {"step": "c", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "C: {{output:p}}"}},
    ]}
    prowl = FakeProwl()
    prowl.fail_on = {"dataforseo_bl_summary"}
    prowl.fail_stops_run = True
    await Orchestrator(prowl, llm, runs_root=tmp_path / "runs", max_workers=2).run(
        "tail-stopped", {"competitors": ["a.com"]}, run_id="hs")
    steps = json.loads((tmp_path / "runs" / "hs" / "checkpoint.json").read_text())["steps"]
    assert not [s["step"] for s in steps if "kept for steps that read" in json.dumps(s)]
