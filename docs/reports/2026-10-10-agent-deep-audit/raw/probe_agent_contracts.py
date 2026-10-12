"""Synthetic offline contract probes. Explicitly collect this file; no xfail.

Run from repo root: PYTHONPATH=tests:. .venv/bin/python -m pytest -q -s
docs/reports/2026-10-10-agent-deep-audit/raw/probe_agent_contracts.py
"""

import os

import pytest
from conftest import FakeLLM, FakeProwl, mini_runbooks_dir, patched_runbooks  # noqa: F401
from mcp.types import CallToolResult

import research_agent.mcp_server as srv
from research_agent.agent.orchestrator import (
    Orchestrator,
    OrchestratorError,
    PlanItem,
    _acquire_run_lock,
)
from research_agent.config import Config
from research_agent.evidence.ledger import ClaimStatus, Ledger
from research_agent.evidence.store import ArtifactStore, Checkpoint
from research_agent.prowl_client import ProwlClient

TOOL = "spyfu_get_domain_stats"
BRIEF = {"competitors": ["example.com"]}


def steps(count=1):
    return {"plan": [
        {"step": f"baseline-{i}", "tool": TOOL, "arguments": {"domain": f"sample-{i}.example.com"}}
        for i in range(count)
    ]}


@pytest.fixture
def wired(monkeypatch, patched_runbooks, tmp_path):  # noqa: F811
    monkeypatch.setenv("RESEARCH_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("RESEARCH_NO_SUBAGENTS", "1")
    config = Config(
        prowl_api_key="test", prowl_mcp_url="http://unused.invalid",
        llm_api_key="test", llm_base_url="http://unused.invalid",
        llm_model="cheap", llm_model_strong="strong",
    )
    monkeypatch.setattr(srv, "_config_from_env", lambda: config)
    monkeypatch.setattr(srv, "_make_prowl", lambda config: FakeProwl())
    monkeypatch.setattr(srv, "_make_llm", lambda config: FakeLLM())
    return tmp_path / "runs"


@pytest.mark.parametrize("entry", ["run", "startup"])
async def test_ka06_non_owner_cannot_mutate_locked_checkpoint(wired, entry):
    store = ArtifactStore(wired / "active-owner")
    store.save_checkpoint(Checkpoint(run_id="active-owner", runbook="mini-teardown"))
    before = store.checkpoint_path.read_bytes()
    fd = _acquire_run_lock(store.run_dir)
    try:
        if entry == "run":
            with pytest.raises(OrchestratorError, match="locked by another process"):
                await srv.research_run("mini-teardown", BRIEF, "active-owner", wait=True)
        else:
            srv._reconcile_orphaned_runs()
        print("KA-06", entry, store.load_checkpoint().status)
        assert store.checkpoint_path.read_bytes() == before
    finally:
        os.close(fd)


def test_ka07_valueless_claim_cannot_erase_numeric_conflict(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    common = {"subject": "example.com monthly traffic", "unit": "visits"}
    a = ledger.add(claim="Traffic is 100", value=100, source_tool="tool_a", **common)
    b = ledger.add(claim="Traffic is 200", value=200, source_tool="tool_b", **common)
    assert a.status == b.status == ClaimStatus.conflict  # negative control
    ledger.add(claim="Traffic exists", source_tool="tool_c", **common)
    print("KA-07", [(c.value, c.status.value) for c in ledger.claims])
    assert a.status == b.status == ClaimStatus.conflict


async def test_ka08_fabricated_verbatim_is_not_verified(tmp_path):
    llm = FakeLLM()
    llm.claims_payload = {"claims": [{
        "claim": "Revenue is USD 999 billion", "subject": "example.com annual revenue",
        "value": 999, "unit": "billion USD", "verbatim": True,
        "source_url": "https://example.invalid/not-in-raw",
    }]}
    raw_path = tmp_path / "raw.json"
    raw_path.write_text('{"rows": []}')
    ledger = Ledger(tmp_path / "ledger.json")
    orch = Orchestrator(FakeProwl(), llm, runs_root=tmp_path)
    await orch._extract_claims(
        PlanItem(step="baseline", tool=TOOL, arguments={}), {"rows": []}, raw_path, ledger
    )
    print("KA-08", [(c.claim, c.status.value) for c in ledger.claims])
    assert not any(c.status == ClaimStatus.verified for c in ledger.claims)


def test_ka09_same_document_is_not_two_independent_sources(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    common = dict(
        claim="Revenue is 100 USD", subject="example.com annual revenue", value=100,
        unit="USD", source_url="https://example.com/annual-report",
    )
    ledger.add(source_tool="web_search", **common)
    ledger.add(source_tool="page_scraper", **common)
    print("KA-09", [(c.source_url, c.status.value) for c in ledger.claims])
    assert all(c.status != ClaimStatus.verified for c in ledger.claims)


@pytest.mark.parametrize("fault", ["raw_write", "extraction"])
async def test_ka10_evidence_failure_cannot_report_complete(wired, monkeypatch, fault):
    llm = FakeLLM()
    llm.plan_payload = steps()
    llm.claims_payload = {"claims": [{
        "claim": "Observed value 42", "value": 42, "unit": "items",
        "subject": "example.com metric", "verbatim": True,
    }]}
    orch = Orchestrator(FakeProwl(), llm, runs_root=wired)
    if fault == "raw_write":
        def fail_write(*args):
            raise OSError("synthetic raw artifact write failure")
        monkeypatch.setattr(ArtifactStore, "save_raw", fail_write)
    else:
        async def fail_extract(*args):
            raise RuntimeError("synthetic extractor failure")
        monkeypatch.setattr(orch, "_extract_claims", fail_extract)
    result = await orch.run("mini-teardown", BRIEF, run_id=fault)
    ledger = Ledger.load(wired / fault / "ledger.json")
    print("KA-10", fault, result.status, len(ledger.claims),
          [os.path.exists(c.raw_ref) for c in ledger.claims])
    assert result.status != "complete"


class ScriptedClient(ProwlClient):
    """Real client billing parsing; only the network boundary is synthetic."""

    def __init__(self, payloads):
        super().__init__(api_key="test", mcp_url="http://unused.invalid")
        self.payloads = iter(payloads)
        self.dispatched = 0
        self.tool_prices = {TOOL: 0.4}

    async def list_tools(self):
        return [TOOL]

    async def tool_info(self, name):
        return {"name": name, "input_schema": {"type": "object"}}

    async def _rpc(self, name, arguments, retry=True):
        self.dispatched += 1
        return CallToolResult(content=[], structuredContent=next(self.payloads))


async def test_ka11_known_cost_does_not_discard_previous_estimates(wired):
    client = ScriptedClient([
        {"rows": [{"value": 42}]},
        {"rows": [{"value": 42}], "billing": {"actual_cost_usd": 0.3}},
        {"rows": [{"value": 42}], "billing": {"actual_cost_usd": 0.1}},
    ])
    llm = FakeLLM()
    llm.plan_payload = steps(3)
    result = await Orchestrator(client, llm, runs_root=wired).run(
        "mini-usd", BRIEF, run_id="mixed-cost"
    )
    print("KA-11", client.dispatched, result.stats)
    # Before call three: estimated first call .4 + known second .3 > budget .5.
    assert client.dispatched == 2


async def test_ka12_billed_failure_cost_survives_resume(wired):
    client = ScriptedClient([{
        "success": False, "error_class": "upstream_error",
        "billing": {"actual_cost_usd": 0.6},
    }])
    llm = FakeLLM()
    llm.plan_payload = steps()
    result = await Orchestrator(client, llm, runs_root=wired).run(
        "mini-usd", BRIEF, run_id="billed-failure"
    )
    assert result.status == "partial"
    assert client.cost_usd == 0.6
    fresh = ScriptedClient([{"rows": [], "billing": {"actual_cost_usd": 0.6}}])
    await Orchestrator(fresh, llm, runs_root=wired).run(
        "mini-usd", BRIEF, run_id="billed-failure"
    )
    print("KA-12", "persisted_cost", result.stats["cost_usd"], "resume_calls", fresh.dispatched)
    assert fresh.dispatched == 0


async def test_control_success_persists_evidence(wired):
    llm = FakeLLM()
    llm.plan_payload = steps()
    llm.claims_payload = {"claims": [{"claim": "Observed value", "value": 42, "unit": "items"}]}
    result = await Orchestrator(FakeProwl(), llm, runs_root=wired).run(
        "mini-teardown", BRIEF, run_id="control"
    )
    ledger = Ledger.load(wired / "control" / "ledger.json")
    assert result.status == "complete"
    assert len(ledger.claims) == 1
    assert os.path.isfile(ledger.claims[0].raw_ref)


async def test_control_known_cost_stops_before_next_dispatch(wired):
    client = ScriptedClient([{"rows": [], "billing": {"actual_cost_usd": 0.6}}])
    llm = FakeLLM()
    llm.plan_payload = steps(3)
    result = await Orchestrator(client, llm, runs_root=wired).run(
        "mini-usd", BRIEF, run_id="budget-control"
    )
    assert result.status == "partial"
    assert client.dispatched == 1


def test_control_unlocked_orphan_is_reconciled(wired):
    store = ArtifactStore(wired / "orphan-control")
    store.save_checkpoint(Checkpoint(run_id="orphan-control", runbook="mini-teardown"))
    srv._reconcile_orphaned_runs()
    assert store.load_checkpoint().status == "interrupted"
