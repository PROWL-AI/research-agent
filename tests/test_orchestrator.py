import json
from pathlib import Path

import pytest

from research_agent.agent.orchestrator import Orchestrator
from research_agent.evidence.ledger import Ledger

from conftest import FakeLLM, FakeProwl


def _plan(steps: int, tool: str = "spyfu_get_domain_stats") -> dict:
    return {
        "plan": [
            {"step": f"step-{i}", "tool": tool, "arguments": {"domain": "x.com"}}
            for i in range(steps)
        ]
    }


@pytest.fixture
def patched_runbooks(monkeypatch, mini_runbooks_dir):
    monkeypatch.setattr("research_agent.runbook.RUNBOOKS_DIR", mini_runbooks_dir)
    return mini_runbooks_dir


async def test_budget_max_tool_calls_stops_execution(
    patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
):
    fake_llm.plan_payload = _plan(3)
    orchestrator = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")

    result = await orchestrator.run(
        "mini-teardown", {"competitors": ["a.com", "b.com"]}, run_id="r1"
    )

    assert result.status == "partial"
    assert result.partial is True
    assert len(fake_prowl.tool_calls) == 2
    assert len(result.skipped_steps) == 1
    assert result.skipped_steps[0]["step"] == "step-2"
    assert "max_tool_calls" in result.skipped_steps[0]["reason"]
    assert Path(result.report_path).is_file()
    assert Path(result.ledger_path).is_file()

    checkpoint = json.loads(
        (tmp_path / "runs" / "r1" / "checkpoint.json").read_text()
    )
    assert checkpoint["status"] == "partial"
    assert checkpoint["counters"]["data_calls"] == 2


async def test_on_error_skip_continues(
    patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
):
    fake_llm.plan_payload = {
        "plan": [
            {"step": "s0", "tool": "spyfu_get_domain_stats", "arguments": {}, "on_error_skip": True},
            {"step": "s1", "tool": "spyfu_get_domain_stats", "arguments": {}},
        ]
    }
    fake_prowl.fail_on.add("spyfu_get_domain_stats")
    orchestrator = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")

    result = await orchestrator.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r2")

    assert result.status == "partial"
    assert len(fake_prowl.tool_calls) == 2
    assert any(s["step"] == "s0" for s in result.skipped_steps)


async def test_hard_failure_aborts_to_writer(
    patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
):
    fake_llm.plan_payload = {
        "plan": [
            {"step": "s0", "tool": "spyfu_get_domain_stats", "arguments": {}},
            {"step": "s1", "tool": "spyfu_get_domain_stats", "arguments": {}},
        ]
    }
    fake_prowl.fail_on.add("spyfu_get_domain_stats")
    orchestrator = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")

    result = await orchestrator.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r3")

    assert result.status == "partial"
    assert len(fake_prowl.tool_calls) == 1
    assert Path(result.report_path).is_file()


async def test_claims_land_in_ledger(
    patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
):
    fake_llm.plan_payload = _plan(2)
    fake_llm.claims_payload = {
        "claims": [
            {
                "claim": "a.com traffic is 42000",
                "subject": "a.com traffic",
                "value": 42000,
                "unit": "visits/month",
                "verbatim": False,
            }
        ]
    }
    orchestrator = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")
    result = await orchestrator.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r4")

    ledger = Ledger.load(Path(result.ledger_path))
    assert len(ledger.claims) == 2
    assert all(c.source_tool == "spyfu_get_domain_stats" for c in ledger.claims)
    assert result.stats["claims"] == 2


async def test_complete_when_within_budget(
    patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
):
    fake_llm.plan_payload = _plan(1)
    orchestrator = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")
    result = await orchestrator.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r5")
    assert result.status == "complete"
    assert result.skipped_steps == []


async def test_resume_skips_completed_steps(
    patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
):
    fake_llm.plan_payload = _plan(2)
    runs = tmp_path / "runs"
    orchestrator = Orchestrator(fake_prowl, fake_llm, runs_root=runs)
    await orchestrator.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r6")

    checkpoint_path = runs / "r6" / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text())
    checkpoint["status"] = "running"
    checkpoint["completed_steps"] = [0]
    checkpoint["counters"]["data_calls"] = 1
    checkpoint_path.write_text(json.dumps(checkpoint))

    fake_prowl.tool_calls.clear()
    orchestrator2 = Orchestrator(fake_prowl, fake_llm, runs_root=runs)
    result = await orchestrator2.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r6")
    assert len(fake_prowl.tool_calls) == 1
    assert result.run_id == "r6"


async def test_max_usd_hard_enforcement_stops_execution(
    patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
):
    fake_llm.plan_payload = _plan(3)
    fake_prowl.cost_per_call = 0.60
    orchestrator = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")

    result = await orchestrator.run("mini-usd", {"competitors": ["a.com"]}, run_id="r-usd")

    assert result.status == "partial"
    assert len(fake_prowl.tool_calls) == 1
    assert any("max_usd" in s["reason"] for s in result.skipped_steps)
    assert result.stats["cost_usd"] == pytest.approx(0.60)


async def test_transform_step_survives_validation():
    from research_agent.agent.orchestrator import validate_plan

    valid = validate_plan(
        [
            {"step": "Baseline", "tool": "spyfu_get_domain_stats", "arguments": {}},
            {"step": "Synthesize", "tool": "transform", "instruction": "compare the two"},
            {"step": "LLM notes", "tool": "LLM_TRANSFORM", "instruction": "x"},
        ],
        allowlist=["spyfu_get_domain_stats"],
        catalog=["spyfu_get_domain_stats"],
    )
    assert [item.step for item in valid] == ["Baseline", "Synthesize", "LLM notes"]


async def test_transform_step_executes_without_tool_call(
    patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
):
    fake_llm.plan_payload = {
        "plan": [
            {"step": "baseline", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "a.com"}},
            {"step": "synthesize", "tool": "transform", "instruction": "compare competitors"},
        ]
    }
    fake_llm.claims_payload = {
        "claims": [{"claim": "a.com is the leader", "subject": "a.com position", "verbatim": False}]
    }
    fake_llm.transform_text = "a.com leads on traffic; b.com on pricing."
    orchestrator = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")

    result = await orchestrator.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r-t1")

    assert result.status == "complete"
    assert len(fake_prowl.tool_calls) == 1
    assert result.stats["data_calls"] == 1

    raw_dir = tmp_path / "runs" / "r-t1" / "raw"
    transform_artifacts = list(raw_dir.glob("01_transform*.md"))
    assert len(transform_artifacts) == 1
    assert transform_artifacts[0].read_text() == fake_llm.transform_text

    checkpoint = json.loads((tmp_path / "runs" / "r-t1" / "checkpoint.json").read_text())
    assert checkpoint["transform_notes"] == [fake_llm.transform_text]

    writer_call = next(
        c for c in fake_llm.calls if c["tier"] == "strong" and not c["json_mode"]
    )
    assert fake_llm.transform_text in writer_call["messages"][1]["content"]

    ledger = Ledger.load(Path(result.ledger_path))
    assert any(c.source_tool == "transform" for c in ledger.claims)


async def test_transform_failure_hard_aborts(
    patched_runbooks, tmp_path: Path, fake_llm: FakeLLM, fake_prowl: FakeProwl
):
    from research_agent.llm import LLMError

    fake_llm.plan_payload = {
        "plan": [{"step": "synthesize", "tool": "transform", "instruction": "x"}]
    }

    async def routed(messages, tier="cheap", json_mode=False, **kwargs):
        if tier == "strong" and json_mode:
            return json.dumps(fake_llm.plan_payload)
        if tier == "cheap" and json_mode:
            return json.dumps(fake_llm.claims_payload)
        if tier == "cheap":
            raise LLMError("transform blew up")
        return fake_llm.report_text

    fake_llm.complete = routed  # type: ignore[assignment]
    orchestrator = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")
    result = await orchestrator.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r-t2")

    assert result.status == "partial"
    assert "transform blew up" in result.skipped_steps[0]["reason"]
    assert len(fake_prowl.tool_calls) == 0
