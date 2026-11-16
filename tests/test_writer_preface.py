"""B-150: a writer answer that thinks aloud before its `# ` title ships only the report.

Seen 2026-11-16 on `pr-79599e56126e9a0c071d` (x-trend-pulse, writer moonshotai/kimi-k3.1-pro): 211 lines of the
model's planning ("I need craft final complete report markdown ...") stood before the report's title in both
report.md and report.html. The lint passed them because they cite real claims.
"""

from pathlib import Path

from research_agent.agent import writer
from research_agent.evidence.ledger import Ledger
from research_agent.runbook import get_runbook

REPORT = "# Pulse (PARTIAL RUN)\n\nOne theme [C1].\n\n## Theme board\n\nRising [C1]."
PREFACE = ("I need craft final complete report markdown complying complex constraints.\n"
           "Should think exact evidence and themes [C1].\n\n")


def _ledger(tmp_path: Path) -> Ledger:
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.add(claim="a.com traffic is 150,000", subject="a.com monthly organic traffic", value=150000,
               unit="visits/month", source_tool="spyfu_get_domain_stats")
    return ledger


class _Queue:
    def __init__(self, responses: list) -> None:
        self.responses = list(responses)

    async def complete(self, messages, tier="cheap", json_mode=False, **kwargs):
        return self.responses.pop(0)


def test_strip_preface_drops_text_before_the_title():
    assert writer.strip_preface(PREFACE + REPORT) == REPORT


def test_strip_preface_keeps_a_report_that_starts_with_its_title():
    assert writer.strip_preface(REPORT) == REPORT
    assert writer.strip_preface("\n\n" + REPORT) == "\n\n" + REPORT


def test_strip_preface_leaves_text_without_a_title_alone():
    # No level-1 title: nothing marks where a report would start, so nothing is cut (B-135 decides on it).
    text = "Some words.\n\n## Section\n\nMore."
    assert writer.strip_preface(text) == text


async def test_write_report_ships_the_report_without_the_preface(patched_runbooks, tmp_path):
    draft = await writer.write_report(
        _Queue([PREFACE + REPORT]), get_runbook("mini-teardown"), _ledger(tmp_path), {"competitors": ["a.com"]},
    )
    assert draft == REPORT
