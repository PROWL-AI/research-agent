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
    assert sent[0] == "a.com" and sent[2] == "b.com"
    checkpoint = _checkpoint(runs, "out")
    scrape = _step(checkpoint, "scrape page")
    raw = (runs / "out" / scrape["raw_ref"]).read_text()
    assert sent[1] == "Analyse this page: " + raw
    analyse = _step(checkpoint, "analyse")
    assert analyse["state"] == "completed"
    assert analyse["arguments"]["domain"].endswith("{{output:scrape_page}}")  # the plan as written
    assert analyse["bound_arguments"] == {"domain": sent[1]}  # the arguments as sent


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

    sent = prowl.tool_calls[1]["arguments"]["domain"]
    assert "[insert your team size here]" in sent  # sent, not refused as template text
    assert sent.endswith("more characters]") and len(sent) < bindings.OUTPUT_CAP + 100
    assert _step(_checkpoint(runs, "page"), "analyse")["state"] == "completed"
