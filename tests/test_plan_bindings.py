"""B-065: a value a later step needs that only an earlier step returns.

Live run accept-subscription-20261021 planned `apple_product` with
`product_id: "{{headspace_apple_id}}"`: the plan is written before any tool
runs, nothing filled the placeholder, and 20 of its 26 skipped steps were the
provider refusing the literal text (each one an attempted call). A transform
before such a step now returns the value in a `bindings` block; a value is kept
only when a raw artifact states it, and a placeholder nobody resolved is never
sent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from research_agent.agent import bindings
from research_agent.agent.orchestrator import Orchestrator

from conftest import FakeLLM, FakeProwl
from test_subagents import _write_runbook

TOOL = "spyfu_get_domain_stats"
BRIEF = {"competitors": ["a.com"]}
APP_ID = "493145008"


@pytest.fixture
def lookup_runbook(patched_runbooks) -> Path:
    _write_runbook(patched_runbooks, "bind-lookup", 60, effort="lookup")
    return patched_runbooks


class IdProwl(FakeProwl):
    """The resolver step returns a store id; every other call the default rows."""

    async def call_tool(self, name: str, arguments: dict[str, Any], idempotency_key: str | None = None) -> Any:
        if arguments.get("domain") == "resolve.com":
            self.tool_calls.append({"name": name, "arguments": arguments, "idempotency_key": idempotency_key})
            self.call_log.append(object())
            return {"results": [{"title": "Headspace", "apple_id": int(APP_ID)}]}
        return await super().call_tool(name, arguments, idempotency_key)


def _plan(*, optional: bool) -> dict:
    later = {"step": "product", "tool": TOOL, "arguments": {"domain": "{{headspace_apple_id}}"}}
    if optional:
        later["on_error_skip"] = True
    return {"plan": [
        {"step": "resolve", "tool": TOOL, "arguments": {"domain": "resolve.com"}},
        {"step": "id map", "tool": "transform", "arguments": {},
         "instruction": "From resolve: give headspace_apple_id"},
        later,
        {"step": "other", "tool": TOOL, "arguments": {"domain": "b.com"}},
    ]}


def _checkpoint(runs: Path, run_id: str) -> dict:
    return json.loads((runs / run_id / "checkpoint.json").read_text())


def _step(checkpoint: dict, name: str) -> dict:
    return next(s for s in checkpoint["steps"] if s["step"] == name)


# ── unit ───────────────────────────────────────────────────────────────────


def test_substitute_fills_whole_and_embedded_placeholders_and_names_the_missing():
    value = {"id": "{{a}}", "q": "app {{a}} vs {{b}}", "ids": ["{{a}}", 7]}
    filled, missing = bindings.substitute(value, {"a": "123"})
    assert filled == {"id": "123", "q": "app 123 vs {{b}}", "ids": ["123", 7]}
    assert missing == {"b"}


def test_an_invalid_placeholder_name_counts_as_unresolved():
    _, missing = bindings.substitute({"id": "{{Headspace ID}}"}, {})
    assert missing == {"Headspace ID"}


def test_parse_keeps_scalars_with_valid_names_from_the_last_block():
    note = ("notes\n```bindings\n{\"a\": \"1\"}\n```\nmore\n```bindings\n"
            "{\"x_id\": 493145008, \"Bad Name\": \"z\", \"obj\": {\"k\": 1}, \"flag\": true}\n```")
    assert bindings.parse(note) == {"x_id": "493145008"}
    assert bindings.parse("no block") == {}
    assert bindings.parse("```bindings\nnot json\n```") == {}
    assert "```bindings" not in bindings.strip_block(note)


def test_grounded_keeps_only_asked_values_an_artifact_states():
    kept, rejected = bindings.grounded(
        {"a_id": "493145008", "b_id": "999999999", "c_id": "123456", "d": "12"},
        ["a_id", "b_id", "d"], ['{"apple_id": 493145008}'])
    assert kept == {"a_id": "493145008"}
    assert set(rejected) == {"b_id", "c_id", "d"}
    assert "not found" in rejected["b_id"] and "not asked" in rejected["c_id"] and "short" in rejected["d"]


# ── run ────────────────────────────────────────────────────────────────────


async def test_a_transform_binds_a_value_and_the_later_step_sends_it(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    prowl = IdProwl()
    llm = FakeLLM()
    llm.plan_payload = _plan(optional=False)
    llm.transform_text = f"Headspace is {APP_ID}.\n```bindings\n{{\"headspace_apple_id\": \"{APP_ID}\"}}\n```"
    await Orchestrator(prowl, llm, runs_root=runs).run("bind-lookup", BRIEF, run_id="bound")

    assert [c["arguments"]["domain"] for c in prowl.tool_calls] == ["resolve.com", APP_ID, "b.com"]
    checkpoint = _checkpoint(runs, "bound")
    assert checkpoint["bindings"] == {"headspace_apple_id": APP_ID}
    product = _step(checkpoint, "product")
    assert product["state"] == "completed"
    assert product["arguments"] == {"domain": "{{headspace_apple_id}}"}  # the plan as written
    assert product["bound_arguments"] == {"domain": APP_ID}  # the arguments as sent
    # the transform was told which names later steps need
    transform_prompt = next(c for c in llm.calls if "Values later steps need" in c["messages"][-1]["content"])
    assert "headspace_apple_id" in transform_prompt["messages"][-1]["content"]
    # the writer reads the prose, not the block
    assert all("```bindings" not in note for note in checkpoint["transform_notes"])


@pytest.mark.parametrize("optional, state", [(True, "skipped_on_error"), (False, "failed")])
async def test_an_unresolved_placeholder_is_never_sent(lookup_runbook, tmp_path, optional, state):
    runs = tmp_path / "runs"
    prowl = IdProwl()
    llm = FakeLLM()
    llm.plan_payload = _plan(optional=optional)
    llm.transform_text = "No id in the artifacts."  # no bindings block
    result = await Orchestrator(prowl, llm, runs_root=runs).run("bind-lookup", BRIEF, run_id=f"unbound-{state}")

    assert [c["arguments"]["domain"] for c in prowl.tool_calls] == ["resolve.com", "b.com"]
    checkpoint = _checkpoint(runs, f"unbound-{state}")
    product = _step(checkpoint, "product")
    assert product["state"] == state
    assert "not sent" in product["reason"] and "{{headspace_apple_id}}" in product["reason"]
    assert product["attempt_ids"] == []  # no attempt, no bill
    assert _step(checkpoint, "other")["state"] == "completed"  # the worker went on
    if not optional:
        assert (result.status, result.terminal_code) == ("partial", "step_failed")


async def test_an_invented_value_is_discarded_and_not_sent(lookup_runbook, tmp_path):
    runs = tmp_path / "runs"
    prowl = IdProwl()
    llm = FakeLLM()
    llm.plan_payload = _plan(optional=True)
    llm.transform_text = "```bindings\n{\"headspace_apple_id\": \"111222333\"}\n```"
    await Orchestrator(prowl, llm, runs_root=runs).run("bind-lookup", BRIEF, run_id="invented")

    assert "111222333" not in [c["arguments"]["domain"] for c in prowl.tool_calls]
    checkpoint = _checkpoint(runs, "invented")
    assert checkpoint["bindings"] == {}
    assert _step(checkpoint, "product")["state"] == "skipped_on_error"


async def test_an_unresolved_placeholder_does_not_count_as_a_refusal(lookup_runbook, tmp_path):
    """Five required unbound steps in a row are not five refusals: nothing was sent."""
    runs = tmp_path / "runs"
    prowl = IdProwl()
    llm = FakeLLM()
    steps = [{"step": f"u{i}", "tool": TOOL, "arguments": {"domain": f"{{{{n{i}}}}}"}} for i in range(6)]
    steps.append({"step": "after", "tool": TOOL, "arguments": {"domain": "b.com"}})
    llm.plan_payload = {"plan": steps}
    await Orchestrator(prowl, llm, runs_root=runs).run("bind-lookup", BRIEF, run_id="no-cascade")
    assert [c["arguments"]["domain"] for c in prowl.tool_calls] == ["b.com"]
    assert _step(_checkpoint(runs, "no-cascade"), "after")["state"] == "completed"


def test_the_planner_is_told_how_to_write_a_placeholder():
    from research_agent.agent.orchestrator import _PLAN_INSTRUCTIONS

    assert "{{snake_case_name}}" in _PLAN_INSTRUCTIONS
    assert "is not sent" in _PLAN_INSTRUCTIONS
