"""B-074: hand a whole earlier output to an LLM-analysis tool.

Live run accept-teardown-20261021b planned `gemini_analyze_website` with the
argument "[substitute full firecrawl_scrape_website output for clickup.com ...]";
the tool "completed" on the literal text, and since B-070 such a step is not sent,
so the analysis was lost. A step now writes ``{{output:<step name>}}``: the stored
raw artifact of that earlier completed step (sha256-checked) is sent, cut at
``bindings.OUTPUT_CAP`` characters with a marker, and a reference to a step that
did not complete is never sent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent.agent import bindings
from research_agent.agent.orchestrator import _PLAN_INSTRUCTIONS as PLANNER_SYSTEM, Orchestrator

from conftest import FakeLLM, FakeProwl
from test_plan_bindings import BRIEF, TOOL
from test_subagents import _write_runbook


@pytest.fixture
def lookup_runbook(patched_runbooks) -> Path:
    _write_runbook(patched_runbooks, "bind-lookup", 60, effort="lookup")
    return patched_runbooks


def _plan(source: str = "scrape page", optional: bool = False) -> dict:
    later = {"step": "analyse", "tool": TOOL, "arguments": {"domain": "Analyse this page: {{output:" + bindings.slug(source) + "}}"}}
    if optional:
        later["on_error_skip"] = True
    return {"plan": [
        {"step": "scrape page", "tool": TOOL, "arguments": {"domain": "a.com"}},
        later,
        {"step": "other", "tool": TOOL, "arguments": {"domain": "b.com"}},
    ]}


def _checkpoint(runs: Path, run_id: str) -> dict:
    return json.loads((runs / run_id / "checkpoint.json").read_text())


def _step(checkpoint: dict, name: str) -> dict:
    return next(s for s in checkpoint["steps"] if s["step"] == name)


def test_output_refs_are_found_and_cut_with_a_marker():
    assert bindings.output_refs({"q": "x {{output:scrape_page}} y", "z": ["{{output:b}}"]}) == {"scrape_page", "b"}
    assert bindings.output_refs({"q": "{{name}}"}) == set()
    text = bindings.output_text("a" * (bindings.OUTPUT_CAP + 50))
    assert len(text) < bindings.OUTPUT_CAP + 80 and text.endswith("[cut: 50 more characters]")
    assert bindings.output_text("short") == "short"
    assert bindings.slug("Scrape page!") == "scrape_page"


async def test_an_earlier_output_is_sent_in_place_of_the_reference(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    prowl = FakeProwl()
    llm = FakeLLM()
    llm.plan_payload = _plan()
    await Orchestrator(prowl, llm, runs_root=runs).run("bind-lookup", BRIEF, run_id="out")

    sent = [c["arguments"]["domain"] for c in prowl.tool_calls]
    assert sent[0] == "a.com" and "b.com" in sent
    analysis = next(d for d in sent if d.startswith("Analyse this page: "))
    checkpoint = _checkpoint(runs, "out")
    scrape = _step(checkpoint, "scrape page")
    raw = json.loads((runs / "out" / scrape["raw_ref"]).read_text())
    assert analysis == "Analyse this page: " + json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    analyse = _step(checkpoint, "analyse")
    assert analyse["state"] == "completed"
    assert analyse["arguments"]["domain"].endswith("{{output:scrape_page}}")  # the plan as written
    assert analyse["bound_arguments"] == {"domain": analysis}  # the arguments as sent


@pytest.mark.parametrize("optional, state", [(True, "skipped_on_error"), (False, "failed")])
async def test_a_reference_to_no_completed_step_is_never_sent(lookup_runbook, tmp_path, optional, state):
    runs = tmp_path / "runs"
    prowl = FakeProwl()
    llm = FakeLLM()
    llm.plan_payload = _plan(source="never planned", optional=optional)
    await Orchestrator(prowl, llm, runs_root=runs).run("bind-lookup", BRIEF, run_id=f"no-out-{state}")

    assert [c["arguments"]["domain"] for c in prowl.tool_calls] == ["a.com", "b.com"]
    analyse = _step(_checkpoint(runs, f"no-out-{state}"), "analyse")
    assert analyse["state"] == state and analyse["attempt_ids"] == []
    assert "not sent" in analyse["reason"] and "{{output:never_planned}}" in analyse["reason"]


def test_the_planner_is_told_how_to_hand_over_an_output():
    assert "{{output:" in PLANNER_SYSTEM and str(bindings.OUTPUT_CAP) in PLANNER_SYSTEM


class PageProwl(FakeProwl):
    """The scrape returns page text that holds a template-like shape of its own."""

    async def call_tool(self, name, arguments, idempotency_key=None):
        if arguments.get("domain") == "a.com":
            self.tool_calls.append({"name": name, "arguments": arguments, "idempotency_key": idempotency_key})
            self.call_log.append(object())
            return {"markdown": "Pricing. [insert your team size here] PLACEHOLDER_TEXT {plan.name} " + "x" * 20_000}
        return await super().call_tool(name, arguments, idempotency_key)


async def test_provider_text_inside_an_output_is_not_judged_as_template_text(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    prowl = PageProwl()
    llm = FakeLLM()
    llm.plan_payload = _plan()
    await Orchestrator(prowl, llm, runs_root=runs).run("bind-lookup", BRIEF, run_id="page")

    sent = next(c["arguments"]["domain"] for c in prowl.tool_calls if c["arguments"]["domain"].startswith("Analyse"))
    assert "[insert your team size here]" in sent  # sent, not refused as template text
    assert sent.endswith("more characters]") and len(sent) < bindings.OUTPUT_CAP + 100
    assert _step(_checkpoint(runs, "page"), "analyse")["state"] == "completed"


# ── seam round 1 ───────────────────────────────────────────────────────────


class SlowProwl(FakeProwl):
    """Yields to the event loop like a real network call, and bills like the server."""

    async def call_tool(self, name, arguments, idempotency_key=None):
        import asyncio
        await asyncio.sleep(0.01)
        if arguments.get("domain") == "a.com":
            self.tool_calls.append({"name": name, "arguments": arguments, "idempotency_key": idempotency_key})
            self.call_log.append(object())
            return {"data": {"page": "ClickUp pricing"}, "execution_time_ms": 812,
                    "billing": {"provider_cost_usd": 0.003, "markup_usd": 0.0012, "debited": 0.0042}}
        return await super().call_tool(name, arguments, idempotency_key)


def _wide_plan() -> dict:
    return {"plan": [
        {"step": "s0", "tool": TOOL, "arguments": {"domain": "c0.com"}},
        {"step": "scrape page", "tool": TOOL, "arguments": {"domain": "a.com"}},
        {"step": "analyse", "tool": TOOL, "arguments": {"domain": "Analyse: {{output:scrape_page}}"}},
        {"step": "s3", "tool": TOOL, "arguments": {"domain": "c3.com"}},
        {"step": "s4", "tool": TOOL, "arguments": {"domain": "c4.com"}},
        {"step": "s5", "tool": TOOL, "arguments": {"domain": "c5.com"}},
    ]}


@pytest.mark.parametrize("workers", [1, 3, 5])
async def test_a_referencing_step_waits_for_the_step_it_names(lookup_runbook, tmp_path, workers):
    """Seam reading: contiguous chunks ran at once, so the analysis started before the scrape."""
    runs = tmp_path / "runs"
    prowl = SlowProwl()
    llm = FakeLLM()
    llm.plan_payload = _wide_plan()
    await Orchestrator(prowl, llm, runs_root=runs, max_workers=workers).run("bind-lookup", BRIEF, run_id=f"w{workers}")
    assert _step(_checkpoint(runs, f"w{workers}"), "analyse")["state"] == "completed"


async def test_the_forwarded_output_carries_no_billing_or_timing(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    prowl = SlowProwl()
    llm = FakeLLM()
    llm.plan_payload = _wide_plan()
    await Orchestrator(prowl, llm, runs_root=runs, max_workers=1).run("bind-lookup", BRIEF, run_id="nobill")
    sent = next(c["arguments"]["domain"] for c in prowl.tool_calls if c["arguments"]["domain"].startswith("Analyse"))
    assert "ClickUp pricing" in sent
    for secret in ("billing", "markup_usd", "provider_cost_usd", "execution_time_ms"):
        assert secret not in sent


async def test_an_ambiguous_or_transform_reference_is_not_sent(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    prowl = FakeProwl()
    llm = FakeLLM()
    llm.plan_payload = {"plan": [
        {"step": "Scrape page", "tool": TOOL, "arguments": {"domain": "a.com"}},
        {"step": "scrape-page", "tool": TOOL, "arguments": {"domain": "a2.com"}},
        {"step": "notes", "tool": "transform", "arguments": {}, "instruction": "Summarise"},
        {"step": "analyse", "tool": TOOL, "arguments": {"domain": "{{output:scrape_page}}"}, "on_error_skip": True},
        {"step": "analyse notes", "tool": TOOL, "arguments": {"domain": "{{output:notes}}"}, "on_error_skip": True},
    ]}
    await Orchestrator(prowl, llm, runs_root=runs, max_workers=1).run("bind-lookup", BRIEF, run_id="ambig")
    checkpoint = _checkpoint(runs, "ambig")
    for name in ("analyse", "analyse notes"):
        record = _step(checkpoint, name)
        assert record["state"] == "skipped_on_error" and record["attempt_ids"] == []


# ── seam round 2 ───────────────────────────────────────────────────────────


def test_only_the_referencing_steps_wait_and_unrelated_steps_stay_with_the_producer():
    from research_agent.agent.subagent import split_segments
    from research_agent.evidence.store import StepRecord

    def rec(i, name, arg="x.com"):
        return StepRecord(step_id=f"s-{i}", raw_index=i, tool=TOOL, step=name, arguments={"domain": arg})
    steps = [rec(0, "s0"), rec(1, "scrape page"), rec(2, "analyse", "{{output:scrape_page}}"),
             rec(3, "s3"), rec(4, "deeper", "{{output:analyse}}"), rec(5, "s5")]
    assert [[r.step for r in seg] for _, seg in split_segments(steps)] == [
        ["s0", "scrape page", "s3", "s5"], ["analyse"], ["deeper"]]


class FailFirstProwl(SlowProwl):
    async def call_tool(self, name, arguments, idempotency_key=None):
        if arguments.get("domain") == "c0.com":
            from research_agent.prowl_client import DispatchOutcomeUnknown
            raise DispatchOutcomeUnknown("transport reset")
        return await super().call_tool(name, arguments, idempotency_key)


async def test_an_unrelated_hard_failure_does_not_strand_the_other_steps(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    llm = FakeLLM()
    llm.plan_payload = _wide_plan()
    await Orchestrator(FailFirstProwl(), llm, runs_root=runs, max_workers=3).run("bind-lookup", BRIEF, run_id="strand")
    checkpoint = _checkpoint(runs, "strand")
    for name in ("s3", "s4", "s5"):
        assert _step(checkpoint, name)["state"] == "completed"


async def test_an_ambiguous_reference_names_the_steps_it_could_mean(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    llm = FakeLLM()
    llm.plan_payload = {"plan": [
        {"step": "Scrape page", "tool": TOOL, "arguments": {"domain": "a.com"}},
        {"step": "scrape-page", "tool": TOOL, "arguments": {"domain": "a2.com"}},
        {"step": "analyse", "tool": TOOL, "arguments": {"domain": "{{output:scrape_page}}"}, "on_error_skip": True},
    ]}
    await Orchestrator(FakeProwl(), llm, runs_root=runs, max_workers=1).run("bind-lookup", BRIEF, run_id="names")
    reason = _step(_checkpoint(runs, "names"), "analyse")["reason"]
    assert "names two steps" in reason and "Scrape page" in reason and "scrape-page" in reason


def test_the_extractor_sees_bound_values_but_not_the_forwarded_page():
    from research_agent.agent.subagent import plan_item
    from research_agent.evidence.store import StepRecord
    record = StepRecord(step_id="s-1", raw_index=1, tool=TOOL, step="analyse",
                        arguments={"url": "{{site_url}}", "q": "{{output:scrape_page}}"},
                        bound_arguments={"url": "https://example.org", "q": "page text naming g2.com"})
    assert plan_item(record, {"site_url": "https://example.org"}).arguments == {"url": "https://example.org", "q": "{{output:scrape_page}}"}
