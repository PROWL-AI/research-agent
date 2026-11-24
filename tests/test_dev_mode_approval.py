"""B-167: in development mode a job starts without a person within the run line; only a job over it waits.

The operator's word of 2026-11-24, relayed by the Fabric CEO after the hanging-approvals audit (request 8bbb6559):
«не должно быть такого, что работа где-то там стопается и зависает»; the run line of 2026-11-17 (USD 100).
"""
from __future__ import annotations

import pytest

from research_agent.service import allowance
from research_agent.service.store import Store

pytestmark = pytest.mark.allowance

RESEARCH = {"kind": "research", "runbook": "market-pulse", "inputs": {"market": "eSIM"}}
CLIENT = {"principal": "client:pipeline", "caller": "client:pipeline", "chain": [], "kid": None, "tier": "client",
          "keyClass": "automated", "dailyUsd": 10.0}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("PROWL_RESEARCH_APPROVAL_MODE", "none")
    return Store(tmp_path)


def job(store, delegation=None, key="k", via="mcp"):
    created, _ = store.create(RESEARCH, key, delegation=delegation, via=via)
    return created


def test_the_default_mode_is_development(monkeypatch):
    monkeypatch.delenv("PROWL_RESEARCH_APPROVAL_MODE", raising=False)
    assert allowance.approval_mode() == "none" and allowance.run_line_usd() == 100.0


def test_an_unknown_mode_is_read_as_the_stricter_one(monkeypatch):
    monkeypatch.setenv("PROWL_RESEARCH_APPROVAL_MODE", "maybe")
    assert allowance.approval_mode() == "operator"


def test_a_dashboard_job_within_the_line_starts_without_a_person(store):
    verdict = allowance.verdict(store, job(store, via="dashboard"))
    assert verdict["by"] == "development-mode" and verdict["principal"] == "operator" and verdict["runLineUsd"] == 100.0


def test_a_client_over_its_daily_ceiling_still_starts_within_the_line(store, monkeypatch):
    monkeypatch.setattr(allowance, "spent_today", lambda *a, **k: 999.0)
    assert allowance.verdict(store, job(store, CLIENT))["by"] == "development-mode"


def test_a_job_over_the_run_line_waits(store, monkeypatch):
    monkeypatch.setenv("PROWL_RESEARCH_RUN_LINE_USD", "1")
    assert allowance.verdict(store, job(store, CLIENT)) is None


def test_production_mode_keeps_the_operator_path(store, monkeypatch):
    monkeypatch.setenv("PROWL_RESEARCH_APPROVAL_MODE", "operator")
    assert allowance.verdict(store, job(store, via="dashboard")) is None


def test_the_decision_records_the_mode(store):
    created = job(store)
    approved = store.decide(created["id"], created["proposal"]["digest"], True,
                            by=allowance.verdict(store, created))
    assert approved["status"] == "working" and approved["decision"]["by"] == "development-mode"
