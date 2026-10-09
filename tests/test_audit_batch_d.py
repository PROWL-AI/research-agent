"""Batch-D audit fixes: runbook and documentation consistency."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNBOOKS = REPO_ROOT / "research_agent" / "runbooks"


def _runbook(name: str) -> str:
    return (RUNBOOKS / name / "SKILL.md").read_text(encoding="utf-8")


def _frontmatter_tools(name: str) -> list[str]:
    text = _runbook(name)
    fm = text.split("---", 2)[1]
    return re.findall(r"^\s+- ([a-z0-9_]+)$", fm, flags=re.M)


class TestTeardownChurnSignals:
    def test_reviews_step_has_churn_variants(self):
        body = _runbook("saas-competitor-teardown")
        assert '"{brand} cancelled"' in body
        assert "switch-from/" in body
        assert "churn-reason evidence" in body

    def test_scorecard_and_battlecard_carry_churn(self):
        body = _runbook("saas-competitor-teardown")
        assert "review velocity, churn signals" in body
        assert "vulnerable / churn signals / what to say" in body


class TestTeardownDropOrder:
    def test_drop_order_references_real_steps(self):
        body = _runbook("saas-competitor-teardown")
        drop_block = body.split("## Budget degradation", 1)[1]
        assert "changelog" not in drop_block
        assert "docs depth" not in drop_block
        assert "tech-stack scan (step 14)" in drop_block


class TestProfitabilityDoctrine:
    CREATIVE_LEVEL = [
        "saas-competitor-teardown",
        "ads-creative-research",
        "idea-validation",
        "subscription-app-audit",
        "domain-baseline",
    ]
    ADVERTISER_LEVEL = [
        "saas-competitor-teardown",
        "growth-signals",
        "channel-economics",
    ]

    def test_no_unqualified_almost_certainly_profitable(self):
        for name in self.CREATIVE_LEVEL + self.ADVERTISER_LEVEL:
            body = _runbook(name)
            for match in re.finditer(r"almost certainly profitable", body):
                tail = body[match.end() : match.end() + 30]
                assert "(advertiser-level)" in tail, f"{name}: untagged claim"

    def test_creative_threshold_is_winner_language(self):
        for name in self.CREATIVE_LEVEL:
            body = _runbook(name)
            assert "60-90+" in body and "creative-level" in body, name

    def test_advertiser_threshold_is_six_months(self):
        for name in self.ADVERTISER_LEVEL:
            body = _runbook(name)
            assert "6+ months" in body and "(advertiser-level)" in body, name


class TestFrontmatterAllowlists:
    def test_declared_tools_are_named_in_the_body(self):
        removed = {
            "ads-creative-research": ["youtube_channel_videos"],
            "channel-economics": ["spyfu_get_domain_stats"],
            "domain-baseline": ["gemini_analyze_website"],
            "seo-site-audit": ["firecrawl_scrape_website", "seo_growth_check_page"],
        }
        for name, tools in removed.items():
            declared = _frontmatter_tools(name)
            for tool in tools:
                assert tool not in declared, f"{name}: {tool} still declared"

    def test_allowlist_tools_appear_in_body(self):
        for skill in sorted(RUNBOOKS.glob("*/SKILL.md")):
            declared = _frontmatter_tools(skill.parent.name)
            body = skill.read_text(encoding="utf-8").split("---", 2)[2]
            unused = [t for t in declared if t not in body]
            assert unused == [], f"{skill.parent.name}: declared but unused: {unused}"


class TestNoDanglingParentRefs:
    def test_runbooks_do_not_reference_parent_guidelines(self):
        for skill in sorted(RUNBOOKS.glob("*/SKILL.md")):
            body = skill.read_text(encoding="utf-8")
            for ref in ("§1.15", "recipe 5.24", "T365", "source guideline"):
                assert ref not in body, f"{skill.parent.name}: dangling ref {ref}"


class TestDomainBaselineBudget:
    def test_optional_markers_and_drop_order(self):
        body = _runbook("domain-baseline")
        assert len(re.findall(r"\*\* \(optional\)", body)) >= 3
        assert "## Budget degradation (drop order)" in body


class TestChannelEconomicsFirstCall:
    def test_media_first_call_wording(self):
        body = _runbook("channel-economics")
        assert "FIRST media call" in body
        assert "FIRST data call" not in body
        assert "before any other data tool" not in body
        assert "first media call" in body


class TestSeoSiteAuditTaskIdRef:
    def test_crawl_reads_point_at_step_7(self):
        body = _runbook("seo-site-audit")
        assert "every step-7 read" in body
        assert "every step-8 read" not in body


class TestKnowledgePack:
    def test_intro_and_tool_count(self):
        text = (REPO_ROOT / "docs" / "knowledge-pack.md").read_text(encoding="utf-8")
        assert "Most traps below have a" in text
        assert "444 active tools" in text
        assert "442 active tools" not in text


class TestReadmeDocs:
    def test_validate_online_flag(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "validate_runbooks.py --online" in readme
        authoring = (REPO_ROOT / "docs" / "runbook-authoring.md").read_text(
            encoding="utf-8"
        )
        assert "validate_runbooks.py --online" in authoring

    def test_runs_dir_scoped_to_mcp(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "MCP server only; the CLI" in readme

    def test_subcommands_listed(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        for token in ("`validate [--online]`", "`rewrite <run_id>`", "`export <run_id>", "--run-id"):
            assert token in readme, token


class TestAuthoringAllowlistGuidance:
    def test_allowlist_range_is_approximate(self):
        authoring = (REPO_ROOT / "docs" / "runbook-authoring.md").read_text(
            encoding="utf-8"
        )
        assert "~20-60 tools" in authoring
