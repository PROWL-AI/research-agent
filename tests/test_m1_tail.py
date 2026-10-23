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
