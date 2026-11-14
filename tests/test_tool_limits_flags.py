"""B-134: a flag the provider takes only with other flags is taken out when they are not set."""
from research_agent.agent import tool_limits

SENT = {"target": "prowl.chat", "max_crawl_pages": 100, "enable_javascript": True, "enable_browser_rendering": True}


def test_browser_rendering_without_load_resources_is_taken_out():
    """pr-ccc142f3e62bfb674bbb: DataForSEO refused the whole crawl (40501) and three reads after it were not sent."""
    assert tool_limits.unmet_flags("dataforseo_onpage_task_post", SENT) == ["enable_browser_rendering"]
    out = tool_limits.canonical("dataforseo_onpage_task_post", SENT)
    assert "enable_browser_rendering" not in out and out["enable_javascript"] is True and out["max_crawl_pages"] == 100


def test_browser_rendering_with_both_requirements_is_sent():
    args = dict(SENT, load_resources=True)
    assert tool_limits.canonical("dataforseo_onpage_task_post", args) == args


def test_other_tools_and_false_flags_are_untouched():
    args = dict(SENT, enable_browser_rendering=False)
    assert tool_limits.canonical("dataforseo_onpage_task_post", args) == args
    assert tool_limits.canonical("spyfu_get_domain_stats", {"domain": "a.com"}) == {"domain": "a.com"}


def test_the_planner_is_told():
    notes = tool_limits.planner_notes(["dataforseo_onpage_task_post"])
    assert "enable_browser_rendering" in notes and "load_resources" in notes
