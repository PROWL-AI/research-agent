"""B-124: a research job's deadline covers its runbook's time budget and the report written after it.

Both acceptance runs of 2026-11-13 (market-pulse, a 20-minute budget) ended `timeout` at the service's 15 minutes,
with their evidence gathered and no report."""
from __future__ import annotations

from research_agent.runbook import get_runbook
from research_agent.service.runtime import REPORT_MARGIN_MINUTES, deadline_minutes


def job(request, minutes=15):
    return {"request": request, "config": {"timeout_minutes": minutes}}


def test_a_research_job_gets_its_runbook_budget_and_the_report_margin():
    budget = get_runbook("market-pulse").meta.budget.max_minutes
    assert deadline_minutes(job({"kind": "research", "runbook": "market-pulse", "inputs": {}})) == budget + REPORT_MARGIN_MINUTES
    assert deadline_minutes(job({"kind": "research", "runbook": "market-pulse@1.0", "inputs": {}})) == budget + REPORT_MARGIN_MINUTES


def test_a_longer_setting_wins():
    assert deadline_minutes(job({"kind": "research", "runbook": "market-pulse", "inputs": {}}, 60)) == 60


def test_tools_tutorials_and_unknown_runbooks_keep_the_setting():
    assert deadline_minutes(job({"kind": "tool", "tool": "google_news", "params": {}})) == 15
    assert deadline_minutes(job({"kind": "tutorial"})) == 15
    assert deadline_minutes(job({"kind": "research", "runbook": "no-such-runbook", "inputs": {}})) == 15


def test_every_shipped_runbook_fits_inside_its_deadline():
    from research_agent.runbook import list_runbooks

    for runbook in list_runbooks():
        name = runbook.meta.name if hasattr(runbook, "meta") else runbook["name"]
        minutes = get_runbook(name).meta.budget.max_minutes
        assert deadline_minutes(job({"kind": "research", "runbook": name, "inputs": {}})) >= minutes + REPORT_MARGIN_MINUTES
