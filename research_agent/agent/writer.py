"""One-shot report writer plus the citation lint gate."""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from research_agent.evidence.ledger import Ledger
from research_agent.llm import LLMClient
from research_agent.runbook import Runbook

log = logging.getLogger(__name__)

_CITATION_RE = re.compile(r"\[C(\d+)\]")
_NUMBER_RE = re.compile(
    r"(?<![\w\d])(?:[$€£]\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?%|\d{1,3}(?:,\d{3})+(?:\.\d+)?"
    r"|\d+(?:\.\d+)?\s?(?:k|K|M|B)\b"
    r"|\d[\d,]*(?:\.\d+)?\s+(?:monthly\s+)?(?:visitors|visits|users|downloads|installs|reviews"
    r"|keywords|backlinks|referring\s+domains|ads|creatives|employees|jobs|queries|mentions"
    r"|revenue|traffic|searches|impressions|clicks))"
)
_CITATION_LOOKAHEAD = 160

WRITER_SYSTEM_TEMPLATE = """\
You are the writer for a research run. Write the final markdown report.

## Runbook output instructions
{output_instructions}

## Runbook verification rules (hard rules — violating them is a failure)
{verification_rules}

## Evidence ledger (the ONLY facts you may use)
{ledger_json}

## Non-negotiable citation rules
- EVERY number in the report must reference a ledger claim id in brackets, e.g. [C12].
- Estimates must carry their error band and a VERIFIED or ASSUMED tag matching the
  ledger claim status.
- Conflicting values are shown as [CONFLICT] with both sides cited — never averaged.
- If the ledger has no evidence for a section, say so explicitly; do not fill gaps
  from general knowledge.
{partial_note}
Write the report now, in markdown."""


class LintIssue(BaseModel):
    kind: str
    text: str
    detail: str


class LintResult(BaseModel):
    issues: list[LintIssue] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def missing_refs(self) -> list[str]:
        return [i.text for i in self.issues if i.kind == "missing_ref"]

    @property
    def uncited_numbers(self) -> list[str]:
        return [i.text for i in self.issues if i.kind == "uncited_number"]


def lint_report(report_md: str, ledger: Ledger) -> LintResult:
    result = LintResult()
    known_ids = {c.id for c in ledger.claims}

    for ref in dict.fromkeys(f"C{n}" for n in _CITATION_RE.findall(report_md)):
        if ref not in known_ids:
            result.issues.append(
                LintIssue(
                    kind="missing_ref",
                    text=ref,
                    detail=f"citation [{ref}] does not exist in the ledger",
                )
            )

    for match in _NUMBER_RE.finditer(report_md):
        window = report_md[max(0, match.start() - _CITATION_LOOKAHEAD):match.end() + _CITATION_LOOKAHEAD]
        if not _CITATION_RE.search(window):
            result.issues.append(
                LintIssue(
                    kind="uncited_number",
                    text=match.group(0).strip(),
                    detail="numeric claim without a nearby [C..] citation",
                )
            )
    return result


async def write_report(
    llm: LLMClient,
    runbook: Runbook,
    ledger: Ledger,
    brief: dict[str, Any],
    *,
    partial: bool = False,
    skipped_steps: list[dict[str, Any]] | None = None,
    transform_notes: list[str] | None = None,
) -> str:
    partial_note = ""
    if partial:
        skipped = ", ".join(s.get("step", "?") for s in skipped_steps or []) or "none"
        partial_note = (
            "\n## PARTIAL RUN\nThis run stopped before completing every planned step. "
            "Mark the report as partial in its first line and list the sections that are "
            f"missing or thin. Skipped steps: {skipped}.\n"
        )

    system = WRITER_SYSTEM_TEMPLATE.format(
        output_instructions=runbook.output_instructions or "(no output instructions)",
        verification_rules=runbook.section("Verification (hard rules)") or "(none)",
        ledger_json=ledger.as_prompt_json(),
        partial_note=partial_note,
    )
    user = (
        "Brief (run inputs):\n"
        + "\n".join(f"- {k}: {v}" for k, v in brief.items())
        + f"\n\nReport template: {runbook.meta.outputs.report_template}"
    )
    if transform_notes:
        user += (
            "\n\n## Transform notes (orchestrator synthesis between tool calls;"
            " use as context, cite the ledger for numbers)\n"
            + "\n\n---\n\n".join(transform_notes)
        )
    return await llm.complete(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        tier="strong",
        max_tokens=8000,
        temperature=0.3,
    )
