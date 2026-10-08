import logging

from research_agent.agent.orchestrator import (
    InputError,
    build_brief,
    normalize_domain,
    validate_plan,
)
from research_agent.runbook import get_runbook

from conftest import load_fixture


def test_normalize_domain_strips_noise():
    assert normalize_domain("https://www.Example.com/pricing?x=1") == "example.com"
    assert normalize_domain("app.linear.app/") == "app.linear.app"
    assert normalize_domain("  Notion.so ") == "notion.so"


def test_normalize_domain_rejects_garbage():
    for bad in ("", "notadomain", "www."):
        try:
            normalize_domain(bad)
        except InputError:
            continue
        raise AssertionError(f"expected InputError for {bad!r}")


def test_build_brief_coerces_and_caps():
    runbook = get_runbook("saas-competitor-teardown")
    brief = build_brief(
        runbook,
        {"competitors": "https://www.Linear.app/x, height.app", "market": "pm tools"},
    )
    assert brief["competitors"] == ["linear.app", "height.app"]
    assert brief["market"] == "pm tools"


def test_build_brief_rejects_over_max():
    runbook = get_runbook("saas-competitor-teardown")
    try:
        build_brief(runbook, {"competitors": [f"d{i}.com" for i in range(6)]})
    except InputError as exc:
        assert "at most 5" in str(exc)
    else:
        raise AssertionError("expected InputError")


def test_build_brief_rejects_unknown_input():
    runbook = get_runbook("saas-competitor-teardown")
    try:
        build_brief(runbook, {"bogus": "x"})
    except InputError as exc:
        assert "unknown inputs" in str(exc)
    else:
        raise AssertionError("expected InputError")


def test_retired_tool_dropped_with_warning(caplog):
    fixture = load_fixture("t3_retired_tool.json")
    with caplog.at_level(logging.WARNING):
        valid, dropped = validate_plan(
            [fixture["plan_item"]],
            fixture["runbook_allowlist"],
            fixture["live_catalog"],
        )
    assert valid == []
    assert dropped and "not in live catalog" in dropped[0]["reason"]
    assert any("not in live catalog" in rec.message for rec in caplog.records)


def test_non_allowlisted_tool_dropped_with_warning(caplog):
    with caplog.at_level(logging.WARNING):
        valid, _ = validate_plan(
            [{"step": "s", "tool": "moz_get_domain_metrics", "arguments": {}}],
            allowlist=["spyfu_get_domain_stats"],
            catalog=["moz_get_domain_metrics", "spyfu_get_domain_stats"],
        )
    assert valid == []
    assert any("not in the runbook allowlist" in rec.message for rec in caplog.records)


def test_valid_plan_items_survive():
    valid, dropped = validate_plan(
        [
            {"step": "a", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "x.com"}},
            {"step": "b", "tool": "dataforseo_bl_summary", "on_error_skip": True},
        ],
        allowlist=["spyfu_get_domain_stats", "dataforseo_bl_summary"],
        catalog=["spyfu_get_domain_stats", "dataforseo_bl_summary"],
    )
    assert dropped == []
    assert [item.step for item in valid] == ["a", "b"]
    assert valid[1].on_error_skip is True
    assert valid[0].arguments == {"domain": "x.com"}
