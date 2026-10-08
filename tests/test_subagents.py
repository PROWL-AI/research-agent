"""Sub-agents (phase 2): parallel workers, segments, compression boundary."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from research_agent.agent.orchestrator import Orchestrator, PlanItem
from research_agent.agent.subagent import (
    EFFORT_WORKERS,
    effort_for,
    partition_workers,
    split_segments,
)
from research_agent.evidence.ledger import Ledger
from research_agent.runbook import RunbookError, load_runbook

from conftest import FakeLLM, FakeProwl


# ── runbook fixtures ─────────────────────────────────────────────────────────

def _write_runbook(directory: Path, name: str, budget_calls: int, effort: str | None = None) -> None:
    effort_line = f'effort: "{effort}"' if effort else ""
    runbook_dir = directory / name
    runbook_dir.mkdir(parents=True)
    (runbook_dir / "SKILL.md").write_text(
        f"""\
---
name: {name}
description: parallel test runbook
version: "1.0"
inputs:
  - {{ name: competitors, type: "list[domain]", required: true, max: 5 }}
tools:
  - spyfu_get_domain_stats
  - dataforseo_bl_summary
budget: {{ max_tool_calls: {budget_calls}, max_usd: 5.00, max_minutes: 30 }}
outputs: {{ report_template: test, formats: [markdown] }}
{effort_line}
---

# Parallel Teardown

## Sequence

1. **Baseline** — tools per competitor.

## Verification (hard rules)

- none

## Output instructions

Template `test`. Required sections:

1. **Executive summary** — key findings.
2. **Source log** — every figure with tool.
""",
        encoding="utf-8",
    )


@pytest.fixture
def para_runbooks(patched_runbooks) -> Path:
    _write_runbook(patched_runbooks, "para-deep", 60)            # deep → 5 workers
    _write_runbook(patched_runbooks, "para-comparison", 20)      # comparison → 3 workers
    _write_runbook(patched_runbooks, "para-lookup", 60, effort="lookup")
    return patched_runbooks


def _data_plan(steps: int, tool: str = "spyfu_get_domain_stats") -> dict:
    return {
        "plan": [
            {"step": f"step-{i}", "tool": tool, "arguments": {"domain": "x.com"}}
            for i in range(steps)
        ]
    }


class ConcurrentFakeProwl(FakeProwl):
    """Counts peak simultaneous in-flight tool calls."""

    def __init__(self, delay: float = 0.02) -> None:
        super().__init__()
        self.delay = delay
        self.in_flight = 0
        self.max_in_flight = 0

    async def call_tool(self, name, arguments):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            return await super().call_tool(name, arguments)
        finally:
            self.in_flight -= 1


# ── pure functions ───────────────────────────────────────────────────────────

class TestEffortMapping:
    def test_budget_derived_classes(self):
        assert effort_for(10) == "lookup"
        assert effort_for(15) == "lookup"
        assert effort_for(16) == "comparison"
        assert effort_for(45) == "comparison"
        assert effort_for(46) == "deep"

    def test_declared_effort_wins(self):
        assert effort_for(90, "lookup") == "lookup"
        assert effort_for(5, "deep") == "deep"

    def test_worker_counts(self):
        assert EFFORT_WORKERS == {"lookup": 1, "comparison": 3, "deep": 5}


class TestPartitionWorkers:
    def _items(self, n: int):
        return [(i, PlanItem(step=f"s{i}", tool="t")) for i in range(n)]

    def test_single_worker_gets_everything(self):
        assert len(partition_workers(self._items(5), 1)) == 1

    def test_contiguous_balanced_chunks(self):
        chunks = partition_workers(self._items(6), 5)
        assert [[i for i, _ in chunk] for chunk in chunks] == [[0, 1], [2], [3], [4], [5]]

    def test_more_workers_than_items(self):
        chunks = partition_workers(self._items(2), 5)
        assert [[i for i, _ in chunk] for chunk in chunks] == [[0], [1]]


class TestSplitSegments:
    def test_transforms_isolate_data_runs(self):
        plan = [
            PlanItem(step="d0", tool="spyfu_get_domain_stats"),
            PlanItem(step="d1", tool="spyfu_get_domain_stats"),
            PlanItem(step="t", tool="transform", instruction="synthesize"),
            PlanItem(step="d2", tool="spyfu_get_domain_stats"),
        ]
        segments = split_segments(plan, set())
        assert [kind for kind, _ in segments] == ["data", "transform", "data"]
        assert [i for i, _ in segments[0][1]] == [0, 1]
        assert [i for i, _ in segments[2][1]] == [3]

    def test_completed_steps_are_left_out(self):
        plan = [PlanItem(step=f"d{i}", tool="spyfu_get_domain_stats") for i in range(3)]
        segments = split_segments(plan, {0, 1})
        assert [i for i, _ in segments[0][1]] == [2]


class TestRunbookEffortField:
    def test_declared_effort_is_accepted(self, para_runbooks: Path):
        rb = load_runbook(para_runbooks / "para-lookup" / "SKILL.md")
        assert rb.meta.effort == "lookup"

    def test_unknown_effort_is_rejected(self, tmp_path: Path):
        _write_runbook(tmp_path, "bad-effort", 10, effort="maximum")
        with pytest.raises(RunbookError, match="unknown effort"):
            load_runbook(tmp_path / "bad-effort" / "SKILL.md")


# ── parallel execution ───────────────────────────────────────────────────────

class TestFanOut:
    async def test_deep_runbook_runs_steps_concurrently(
        self, para_runbooks: Path, tmp_path: Path, fake_llm: FakeLLM
    ):
        prowl = ConcurrentFakeProwl()
        fake_llm.plan_payload = _data_plan(6)
        orch = Orchestrator(prowl, fake_llm, runs_root=tmp_path / "runs")

        result = await orch.run("para-deep", {"competitors": ["a.com"]}, run_id="p1")

        assert result.status == "complete"
        assert len(prowl.tool_calls) == 6
        assert prowl.max_in_flight > 1, "expected parallel tool calls"
        checkpoint = json.loads((tmp_path / "runs" / "p1" / "checkpoint.json").read_text())
        segment = checkpoint["stats"]["worker_segments"][0]
        assert segment["workers"] == 5
        assert segment["done"] == 6

    async def test_declared_lookup_stays_sequential(
        self, para_runbooks: Path, tmp_path: Path, fake_llm: FakeLLM
    ):
        prowl = ConcurrentFakeProwl()
        fake_llm.plan_payload = _data_plan(4)
        orch = Orchestrator(prowl, fake_llm, runs_root=tmp_path / "runs")

        await orch.run("para-lookup", {"competitors": ["a.com"]}, run_id="p2")

        assert prowl.max_in_flight == 1

    async def test_env_escape_hatch_disables_subagents(
        self, para_runbooks: Path, tmp_path: Path, fake_llm: FakeLLM, monkeypatch
    ):
        monkeypatch.setenv("RESEARCH_NO_SUBAGENTS", "1")
        prowl = ConcurrentFakeProwl()
        fake_llm.plan_payload = _data_plan(4)
        orch = Orchestrator(prowl, fake_llm, runs_root=tmp_path / "runs")

        await orch.run("para-deep", {"competitors": ["a.com"]}, run_id="p3")

        assert prowl.max_in_flight == 1

    async def test_transform_waits_for_the_whole_segment(
        self, para_runbooks: Path, tmp_path: Path, fake_llm: FakeLLM
    ):
        prowl = ConcurrentFakeProwl()
        fake_llm.plan_payload = {
            "plan": [
                {"step": "d0", "tool": "spyfu_get_domain_stats", "arguments": {}},
                {"step": "d1", "tool": "dataforseo_bl_summary", "arguments": {}},
                {"step": "synth", "tool": "transform", "instruction": "merge baselines"},
                {"step": "d2", "tool": "spyfu_get_domain_stats", "arguments": {}},
            ]
        }
        orch = Orchestrator(prowl, fake_llm, runs_root=tmp_path / "runs")

        result = await orch.run("para-deep", {"competitors": ["a.com"]}, run_id="p4")

        assert result.status == "complete"
        assert len(prowl.tool_calls) == 3
        # The transform's cheap non-JSON call comes after both segment extractions.
        cheap_text_calls = [
            c for c in fake_llm.calls if c["tier"] == "cheap" and not c["json_mode"]
        ]
        cheap_json_calls = [
            c for c in fake_llm.calls if c["tier"] == "cheap" and c["json_mode"]
        ]
        assert len(cheap_text_calls) == 1  # exactly one transform
        assert len(cheap_json_calls) >= 2  # extractions for d0/d1 happened
        checkpoint = json.loads((tmp_path / "runs" / "p4" / "checkpoint.json").read_text())
        assert checkpoint["transform_notes"] == ["Transform synthesis notes."]


class TestFailureSemantics:
    async def test_hard_failure_stops_only_its_worker(
        self, para_runbooks: Path, tmp_path: Path, fake_llm: FakeLLM
    ):
        prowl = FakeProwl()
        prowl.fail_on.add("spyfu_get_domain_stats")
        fake_llm.plan_payload = {
            "plan": [
                {"step": "bad-0", "tool": "spyfu_get_domain_stats", "arguments": {}},
                {"step": "good-1", "tool": "dataforseo_bl_summary", "arguments": {}},
                {"step": "bad-2", "tool": "spyfu_get_domain_stats", "arguments": {}},
                {"step": "good-3", "tool": "dataforseo_bl_summary", "arguments": {}},
            ]
        }
        orch = Orchestrator(prowl, fake_llm, runs_root=tmp_path / "runs")

        result = await orch.run("para-deep", {"competitors": ["a.com"]}, run_id="p5")

        assert result.partial is True
        assert len(prowl.tool_calls) == 4  # every worker attempted its step
        failed = {s["step"] for s in result.skipped_steps}
        assert {"bad-0", "bad-2"} <= failed
        checkpoint = json.loads((tmp_path / "runs" / "p5" / "checkpoint.json").read_text())
        assert checkpoint["counters"]["data_calls"] == 2  # only the good ones counted

    async def test_on_error_skip_inside_worker(
        self, para_runbooks: Path, tmp_path: Path, fake_llm: FakeLLM
    ):
        prowl = FakeProwl()
        prowl.fail_on.add("spyfu_get_domain_stats")
        fake_llm.plan_payload = {
            "plan": [
                {"step": "s0", "tool": "spyfu_get_domain_stats", "arguments": {}, "on_error_skip": True},
                {"step": "s1", "tool": "dataforseo_bl_summary", "arguments": {}},
            ]
        }
        orch = Orchestrator(prowl, fake_llm, runs_root=tmp_path / "runs")

        result = await orch.run("para-deep", {"competitors": ["a.com"]}, run_id="p6")

        assert result.status == "complete"
        assert len(result.skipped_steps) == 1
        assert result.skipped_steps[0]["step"] == "s0"

    async def test_budget_stop_discloses_everything_reachable(
        self, para_runbooks: Path, tmp_path: Path, fake_llm: FakeLLM
    ):
        prowl = FakeProwl()
        fake_llm.plan_payload = _data_plan(6)
        # comparison runbook: budget 20 → 3 workers; shrink via plan? No —
        # use the deep runbook but a tight *plan-time* budget is not settable,
        # so reuse mini-teardown semantics: budget 2 in the mini fixture.
        orch = Orchestrator(prowl, fake_llm, runs_root=tmp_path / "runs")

        result = await orch.run("mini-teardown", {"competitors": ["a.com", "b.com"]}, run_id="p7")

        assert result.partial is True
        assert len(prowl.tool_calls) == 2
        skipped = {s["step"] for s in result.skipped_steps}
        assert skipped == {f"step-{i}" for i in range(2, 6)}


class TestResume:
    async def test_completed_steps_are_not_reexecuted(
        self, para_runbooks: Path, tmp_path: Path, fake_llm: FakeLLM
    ):
        prowl = FakeProwl()
        runs = tmp_path / "runs"
        (runs / "p8").mkdir(parents=True)
        (runs / "p8" / "checkpoint.json").write_text(json.dumps({
            "run_id": "p8",
            "runbook": "para-deep",
            "status": "running",
            "brief": {"competitors": ["a.com"]},
            "plan": _data_plan(4)["plan"],
            "completed_steps": [0, 1],
            "counters": {"data_calls": 2, "cost_usd": None},
        }))
        orch = Orchestrator(prowl, fake_llm, runs_root=runs)

        result = await orch.run("para-deep", {"competitors": ["a.com"]}, run_id="p8")

        assert len(prowl.tool_calls) == 2
        assert result.status == "complete"


class TestCompressionBoundary:
    async def test_only_claims_and_files_cross_the_boundary(
        self, para_runbooks: Path, tmp_path: Path, fake_llm: FakeLLM
    ):
        prowl = FakeProwl()
        fake_llm.plan_payload = _data_plan(4)
        fake_llm.claims_payload = {
            "claims": [{"claim": "x.com has 42 backlinks", "subject": "x.com backlinks",
                        "value": "42", "unit": "backlinks", "verbatim": False}]
        }
        orch = Orchestrator(prowl, fake_llm, runs_root=tmp_path / "runs")

        result = await orch.run("para-deep", {"competitors": ["a.com"]}, run_id="p9")

        ledger = Ledger.load(Path(result.ledger_path))
        assert len(ledger.claims) == 4  # one per step
        raw_files = list((tmp_path / "runs" / "p9" / "raw").glob("*.json"))
        assert len(raw_files) == 4
        checkpoint = json.loads((tmp_path / "runs" / "p9" / "checkpoint.json").read_text())
        assert checkpoint["stats"]["worker_segments"][0]["claims"] == 4
