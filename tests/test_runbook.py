from pathlib import Path

import pytest

from research_agent.runbook import (
    RunbookError,
    get_runbook,
    list_runbooks,
    load_runbook,
)


def test_flagship_runbook_loads():
    runbook = get_runbook("saas-competitor-teardown")
    assert runbook.meta.name == "saas-competitor-teardown"
    assert runbook.meta.budget.max_tool_calls == 90
    assert runbook.meta.budget.max_usd == 3.00
    assert runbook.meta.budget.max_minutes == 30
    assert len(runbook.meta.tools) == 53
    competitors = next(i for i in runbook.meta.inputs if i.name == "competitors")
    assert competitors.type == "list[domain]"
    assert competitors.max == 5
    assert runbook.output_instructions


def test_list_runbooks_includes_flagship():
    names = [rb.name for rb in list_runbooks()]
    assert "saas-competitor-teardown" in names


def test_unknown_frontmatter_key_rejected(tmp_path: Path):
    path = tmp_path / "SKILL.md"
    path.write_text(
        """\
---
name: broken
description: x
version: "1.0"
tools: [a]
budget: { max_tool_calls: 1, max_usd: 1.0, max_minutes: 1 }
outputs: { report_template: t, formats: [markdown] }
surprise_key: nope
---

body
""",
        encoding="utf-8",
    )
    with pytest.raises(RunbookError, match="invalid frontmatter"):
        load_runbook(path)


def test_missing_required_key_rejected(tmp_path: Path):
    path = tmp_path / "SKILL.md"
    path.write_text(
        """\
---
name: broken
description: x
version: "1.0"
tools: [a]
outputs: { report_template: t, formats: [markdown] }
---

body
""",
        encoding="utf-8",
    )
    with pytest.raises(RunbookError, match="invalid frontmatter"):
        load_runbook(path)


def test_unknown_input_type_rejected(tmp_path: Path):
    path = tmp_path / "SKILL.md"
    path.write_text(
        """\
---
name: broken
description: x
version: "1.0"
inputs:
  - { name: thing, type: "url", required: true }
tools: [a]
budget: { max_tool_calls: 1, max_usd: 1.0, max_minutes: 1 }
outputs: { report_template: t, formats: [markdown] }
---

body
""",
        encoding="utf-8",
    )
    with pytest.raises(RunbookError, match="unknown type"):
        load_runbook(path)


def test_get_runbook_unknown_name():
    with pytest.raises(RunbookError, match="unknown runbook"):
        get_runbook("does-not-exist")
