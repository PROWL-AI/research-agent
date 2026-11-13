"""B-108, rule R30: a report a person reads is held to the copy rules of the agents database's `copy-check` pattern.

The live acceptance of 2026-11-13 found 6 and 25 em dashes in the two reports, the writer's own partial banner
included. The writer prompt of version 1 carried 22 of them and asked for a marker that holds one. Version 2 carries
none and the pattern's copy-rule line; the writer's lint adds the pattern's AT-06 and AT-16 findings and the repair pass
fixes them. Version 1 stays as it shipped (R28) and writes again with `RESEARCH_WRITER_PROMPT=1`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from research_agent.agent import writer
from research_agent.agent.writer import (
    REPAIR_SYSTEM_TEMPLATE,
    REPAIR_SYSTEM_TEMPLATE_V2,
    WRITER_SYSTEM_TEMPLATE,
    WRITER_SYSTEM_TEMPLATE_V2,
    copy_rule_issues,
    lint_report,
    write_and_repair,
)
from research_agent.evidence.ledger import Ledger
from research_agent.runbook import get_runbook

DASH = chr(0x2014)
VENDORED = Path(__file__).resolve().parent.parent / "research_agent" / "agent" / "copy_check.py"


def _ledger(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.add(claim="a.com traffic is 150,000", subject="a.com monthly organic traffic", value=150000,
               unit="visits/month", source_tool="spyfu_get_domain_stats")
    return ledger


class _Queue:
    def __init__(self, *answers):
        self.answers, self.systems = list(answers), []

    async def complete(self, messages, tier="cheap", json_mode=False, **kwargs):
        self.systems.append(messages[0]["content"])
        return self.answers.pop(0)


def test_the_vendored_pattern_names_its_version():
    assert VENDORED.read_text().splitlines()[0] == "# vendored from patterns/copy-check/code/copy_check.py@1.1.0"


def test_version_2_prompts_carry_no_dash_and_the_patterns_copy_rule_line():
    assert DASH not in WRITER_SYSTEM_TEMPLATE_V2 and DASH not in REPAIR_SYSTEM_TEMPLATE_V2
    assert "{copy_rules}" in WRITER_SYSTEM_TEMPLATE_V2 and "{copy_rules}" in REPAIR_SYSTEM_TEMPLATE_V2
    assert DASH in WRITER_SYSTEM_TEMPLATE and DASH in REPAIR_SYSTEM_TEMPLATE  # version 1 as it shipped (R28)


def test_dashes_are_found_on_prose_lines_and_never_in_charts_or_tables():
    report = (f"# Title\n**PARTIAL RUN {DASH} missing:** demand\nx -- y\n```chart\n{{\"title\": \"a {DASH} b\"}}\n```\n"
              "| a | b |\n|---|---|\n- a list item\nrange 2020-2024")
    issues = copy_rule_issues(report)
    assert [i.context for i in issues] == [f"**PARTIAL RUN {DASH} missing:** demand", "x -- y"]
    assert all(i.kind == "copy_rule" and i.detail.startswith("AT-06") for i in issues)


def test_both_assumption_markers_cover_a_figure(tmp_path):
    ledger = _ledger(tmp_path)
    for marker in ("(target, assumption, not data)", f"(target, assumption {DASH} not data)"):
        assert lint_report(f"Aim for 5% CTR {marker}.", ledger).ok


async def test_version_2_repairs_a_dash_the_draft_wrote(tmp_path, monkeypatch):
    monkeypatch.delenv("RESEARCH_WRITER_PROMPT", raising=False)
    draft = f"# Report\n\nTraffic is 150,000 visits [C1] {DASH} a steady base.\n"
    llm = _Queue(draft, "L2: Traffic is 150,000 visits [C1], a steady base.")
    outcome = await write_and_repair(llm, get_runbook("market-pulse"), _ledger(tmp_path), {"market": "x"})
    assert DASH not in outcome.report_md and outcome.lint_after == 0 and outcome.prompt_version == "2"
    # The template carries no dash; a shipped runbook's own instructions still may (R28), and the lint catches what
    # the model copies from them.
    assert "AT-06" in llm.systems[0] and DASH not in llm.systems[0].split("## Runbook output instructions")[0]


async def test_version_1_writes_as_it_shipped(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_WRITER_PROMPT", "1")
    draft = f"# Report\n\nTraffic is 150,000 visits [C1] {DASH} a steady base.\n"
    outcome = await write_and_repair(_Queue(draft), get_runbook("market-pulse"), _ledger(tmp_path), {"market": "x"})
    assert outcome.report_md == draft and outcome.prompt_version == "1"


def test_an_unknown_version_is_refused(monkeypatch):
    monkeypatch.setenv("RESEARCH_WRITER_PROMPT", "9")
    with pytest.raises(ValueError):
        writer.writer_prompt_version()
