"""B-070 and B-071: arguments a provider refuses and bills are never sent.

B-065 stopped an unresolved ``{{name}}`` from being sent. The saved runs show the
planner writing template text in other shapes too, and the provider taking each one
as a value: refused and billed, or worse, "completed" (gemini_analyze_website read
the literal "[substitute full firecrawl_scrape_website output ...]" on
accept-teardown-20261021b and its answer became claims). Every argument below is
copied from a saved run. B-071: `tiktok_ads_library` refuses `country: "US"` (HTTP
400, five billed calls on accept-subscription-20261021 and -b) while its schema
offers 'US' as the example.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent.agent import bindings, tool_limits
from research_agent.agent.orchestrator import Orchestrator

from conftest import FakeLLM, FakeProwl
from test_subagents import _write_runbook

TOOL = "spyfu_get_domain_stats"
BRIEF = {"competitors": ["a.com"]}

#: Arguments that were sent on live runs and are template text, not values.
SENT_TEMPLATES = [
    "[substitute landing_page_url of the longest-running active monday.com ad from transform_ads_health]",
    "[substitute full firecrawl_scrape_website output for clickup.com from the scrape_clickup step]",
    "<video_id from youtube_search result — most recent official Novo Nordisk investor call>",
    "<governance / remuneration report URL from search or IR map>",
    "{youtube_search.latest_official_call_video_id}",
    "PLACEHOLDER_FROM_STEP_22",
]

#: Real values the same runs sent; none of them is template text.
REAL_VALUES = [
    '"Novo Nordisk" going concern',
    "Novo Nordisk auditor resigned OR going concern OR restatement",
    "site:reddit.com headspace [2026]",
    "placeholder text generator",
    "https://www.novonordisk.com/investors.html",
    '{"a": 1}',
    "price < 10 from 5 > 2",
    "https://apps.apple.com/us/app/id{{balance_apple_id}}",  # a {{name}}: B-065's path, not this one
    # shapes the unit verifier found the first patterns flagged (2026-10-22)
    "input[placeholder='Email']",
    "<input placeholder='Search'>",
    "[Substitute Teacher] movie",
    "how to [insert] a row",
    "[fill in the blank] worksheet",
    "<john@from.com>",
]


@pytest.mark.parametrize("value", SENT_TEMPLATES)
def test_template_text_seen_on_live_runs_is_found(value):
    assert bindings.template_text({"arg": value}) == [value]
    assert bindings.template_text({"nested": [{"url": f"https://x.com/{value}"}]})


@pytest.mark.parametrize("value", REAL_VALUES)
def test_real_values_are_not_template_text(value):
    assert bindings.template_text({"arg": value}) == []


def test_template_text_stays_linear_on_a_long_argument():
    """An unbounded pattern took 30 s on 136 KB and stalled every worker of the segment."""
    import time

    value = "<a " + "data from source " * 8000
    started = time.perf_counter()
    bindings.template_text({"a": value})
    assert time.perf_counter() - started < 0.5


def test_the_tiktok_country_limit_refuses_us_and_takes_all_and_europe():
    assert tool_limits.refused("tiktok_ads_library", {"query": "Calm", "country": "US"}) == ["country='US'"]
    for ok in ("all", "DE", "GB"):
        assert tool_limits.refused("tiktok_ads_library", {"query": "Calm", "country": ok}) == []
    assert tool_limits.refused("tiktok_ads_library", {"query": "Calm"}) == []  # the provider default
    assert tool_limits.refused("meta_ad_library", {"country": "US"}) == []  # no limit known: sent


def test_the_planner_is_told_the_limits_of_its_runbook_tools():
    notes = tool_limits.planner_notes(["meta_ad_library", "tiktok_ads_library"])
    assert notes.startswith("- `tiktok_ads_library` `country`:") and "`all`" in notes
    assert tool_limits.planner_notes(["meta_ad_library"]) == ""


# ── run ────────────────────────────────────────────────────────────────────


@pytest.fixture
def lookup_runbook(patched_runbooks) -> Path:
    _write_runbook(patched_runbooks, "notsent-lookup", 60, effort="lookup")
    return patched_runbooks


@pytest.fixture
def domain_limit(monkeypatch):
    """A known limit on the test tool, so a run exercises the dispatch guard."""
    limit = tool_limits.ArgumentLimit(allowed=frozenset({"a.com", "b.com"}), note="only a.com or b.com",
                                      source="test")
    monkeypatch.setitem(tool_limits.LIMITS, TOOL, {"domain": limit})


def _checkpoint(runs: Path, run_id: str) -> dict:
    return json.loads((runs / run_id / "checkpoint.json").read_text())


def _step(checkpoint: dict, name: str) -> dict:
    return next(s for s in checkpoint["steps"] if s["step"] == name)


@pytest.mark.parametrize("optional, state", [(True, "skipped_on_error"), (False, "failed")])
async def test_a_step_with_template_text_is_never_sent(lookup_runbook, tmp_path, optional, state):
    runs = tmp_path / "runs"
    prowl = FakeProwl()
    llm = FakeLLM()
    templated = {"step": "templated", "tool": TOOL, "arguments": {"domain": SENT_TEMPLATES[0]}}
    if optional:
        templated["on_error_skip"] = True
    llm.plan_payload = {"plan": [templated, {"step": "after", "tool": TOOL, "arguments": {"domain": "b.com"}}]}
    result = await Orchestrator(prowl, llm, runs_root=runs).run("notsent-lookup", BRIEF, run_id=f"tpl-{state}")

    assert [c["arguments"]["domain"] for c in prowl.tool_calls] == ["b.com"]
    step = _step(_checkpoint(runs, f"tpl-{state}"), "templated")
    assert step["state"] == state
    assert "not sent" in step["reason"] and "template text" in step["reason"]
    assert step["attempt_ids"] == []  # no attempt, no bill
    if not optional:
        assert (result.status, result.terminal_code) == ("partial", "step_failed")


async def test_a_value_the_provider_is_known_to_refuse_is_never_sent(lookup_runbook, tmp_path, domain_limit):
    runs = tmp_path / "runs"
    prowl = FakeProwl()
    llm = FakeLLM()
    llm.plan_payload = {"plan": [
        {"step": "refused", "tool": TOOL, "arguments": {"domain": "us.com"}, "on_error_skip": True},
        {"step": "after", "tool": TOOL, "arguments": {"domain": "b.com"}},
    ]}
    await Orchestrator(prowl, llm, runs_root=runs).run("notsent-lookup", BRIEF, run_id="limit")

    assert [c["arguments"]["domain"] for c in prowl.tool_calls] == ["b.com"]
    step = _step(_checkpoint(runs, "limit"), "refused")
    assert step["state"] == "skipped_on_error"
    assert step["reason"] == f"not sent: {TOOL} does not take domain='us.com' (a known provider limit)"
    assert step["attempt_ids"] == []


async def test_not_sent_steps_do_not_count_as_refusals(lookup_runbook, tmp_path):
    """Six required template-text steps in a row are not six refusals: nothing was sent."""
    runs = tmp_path / "runs"
    prowl = FakeProwl()
    llm = FakeLLM()
    steps = [{"step": f"t{i}", "tool": TOOL, "arguments": {"domain": f"PLACEHOLDER_FROM_STEP_{i}"}} for i in range(6)]
    steps.append({"step": "after", "tool": TOOL, "arguments": {"domain": "b.com"}})
    llm.plan_payload = {"plan": steps}
    await Orchestrator(prowl, llm, runs_root=runs).run("notsent-lookup", BRIEF, run_id="no-cascade")
    assert [c["arguments"]["domain"] for c in prowl.tool_calls] == ["b.com"]
    assert _step(_checkpoint(runs, "no-cascade"), "after")["state"] == "completed"


async def test_the_planner_prompt_carries_the_limits_of_allowlisted_tools(lookup_runbook, tmp_path, domain_limit):
    llm = FakeLLM()
    llm.plan_payload = {"plan": [{"step": "s", "tool": TOOL, "arguments": {"domain": "a.com"}}]}
    await Orchestrator(FakeProwl(), llm, runs_root=tmp_path / "runs").run("notsent-lookup", BRIEF, run_id="prompt")
    planner = next(c for c in llm.calls if "Output the plan JSON now." in c["messages"][-1]["content"])
    assert "## Argument limits the schemas do not state" in planner["messages"][-1]["content"]
    assert "only a.com or b.com" in planner["messages"][-1]["content"]
