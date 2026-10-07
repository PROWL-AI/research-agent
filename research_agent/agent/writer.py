"""One-shot report writer plus the citation lint gate."""

from __future__ import annotations

import logging
import re
from pathlib import Path
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

## RULE 0 — CITATIONS (the hardest rule; violating it fails the report)
- EVERY number, percentage, dollar figure, count, or date-range claim carries
  its [C..] reference IMMEDIATELY after the figure. The Source Log table does
  NOT substitute for inline citations.
- Check the claim's subject before citing. Citing [C20] for a figure about a
  different entity than C20's subject is WORSE than not citing at all.
- If no ledger claim supports a figure, delete the figure or mark it
  [UNVERIFIED]. NEVER invent a citation.
- When two ledger claims conflict on the same subject, cite BOTH with
  [CONFLICT] — never average them silently.

WRONG: "Their channel has 430K subscribers [C20]."
       (C20's subject is a different brand's channel — subject mismatch)
WRONG: "The video has 113K+ views."
       (bare number; the only nearby claim holds a duration, not views)
RIGHT: "Their channel has 430K subscribers [C17] (VERIFIED)."
       (C17's subject is this brand's channel subscriber count)

## Runbook output instructions
{output_instructions}

## Runbook verification rules (hard rules — violating them is a failure)
{verification_rules}

## Evidence ledger (the ONLY facts you may use)
{ledger_json}

## More citation rules (all subordinate to RULE 0)
- Estimates must carry their error band and a VERIFIED or ASSUMED tag matching the
  ledger claim status.
- If the ledger has no evidence for a section, say so explicitly; do not fill gaps
  from general knowledge.
{partial_note}
Write the report now, in markdown."""


REPAIR_SYSTEM_TEMPLATE = """\
You are the citation-repair pass for a research report. The draft below failed
citation lint; fix EVERY listed issue.

Rules:
- For each uncited number: attach the correct [C..] citation from the ledger
  IMMEDIATELY after the figure — but ONLY if the ledger claim's subject matches
  what the sentence states. Check the subject before citing; citing a claim
  about a different entity is worse than not citing.
- If no ledger claim supports a figure, do NOT invent a citation: delete the
  figure or mark it as [UNVERIFIED] text.
- For each missing_ref (a [C..] that does not exist in the ledger): replace it
  with the correct claim id, or remove/mark the figure as above.
- Where two ledger claims conflict on the same subject, cite BOTH with
  [CONFLICT].
- Change nothing else: structure, sections, and already-correct text stay
  exactly as they are.

## Evidence ledger (the ONLY source of valid claim ids)
{ledger_json}

Output the full repaired report in markdown."""


class WriterOutcome(BaseModel):
    report_md: str
    lint_before: int
    lint_after: int
    revised: bool


class RewriteError(Exception):
    pass


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


async def repair_report(
    llm: LLMClient,
    draft: str,
    lint: LintResult,
    ledger: Ledger,
) -> str:
    issues = "\n".join(
        f"- {issue.kind}: {issue.text!r} — {issue.detail}" for issue in lint.issues
    )
    system = REPAIR_SYSTEM_TEMPLATE.format(ledger_json=ledger.as_prompt_json())
    user = f"## Lint issues to fix\n{issues}\n\n## Draft report\n{draft}"
    return await llm.complete(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        tier="strong",
        max_tokens=8000,
        temperature=0.2,
    )


async def write_and_repair(
    llm: LLMClient,
    runbook: Runbook,
    ledger: Ledger,
    brief: dict[str, Any],
    *,
    partial: bool = False,
    skipped_steps: list[dict[str, Any]] | None = None,
    transform_notes: list[str] | None = None,
) -> WriterOutcome:
    draft = await write_report(
        llm, runbook, ledger, brief,
        partial=partial, skipped_steps=skipped_steps, transform_notes=transform_notes,
    )
    lint_before = lint_report(draft, ledger)
    if lint_before.ok:
        return WriterOutcome(report_md=draft, lint_before=0, lint_after=0, revised=False)
    log.info(
        "writer draft failed lint (%d issues); running one repair pass",
        len(lint_before.issues),
    )
    repaired = await repair_report(llm, draft, lint_before, ledger)
    lint_after = lint_report(repaired, ledger)
    if lint_after.issues:
        log.warning(
            "repair pass left %d lint issues (was %d)",
            len(lint_after.issues), len(lint_before.issues),
        )
    return WriterOutcome(
        report_md=repaired,
        lint_before=len(lint_before.issues),
        lint_after=len(lint_after.issues),
        revised=True,
    )


async def rewrite_report(
    llm: LLMClient, runs_root: Path, run_id: str
) -> WriterOutcome:
    from research_agent.evidence.store import ArtifactStore
    from research_agent.runbook import get_runbook

    run_dir = Path(runs_root) / run_id
    store = ArtifactStore(run_dir)
    checkpoint = store.load_checkpoint()
    if checkpoint is None:
        raise RewriteError(f"run '{run_id}' has no checkpoint at {run_dir}")
    ledger_path = run_dir / "ledger.json"
    if not ledger_path.is_file():
        raise RewriteError(
            f"run '{run_id}' has no ledger.json — nothing to write from"
        )
    ledger = Ledger.load(ledger_path)
    runbook = get_runbook(checkpoint.runbook)
    outcome = await write_and_repair(
        llm, runbook, ledger, checkpoint.brief,
        partial=checkpoint.partial,
        skipped_steps=checkpoint.skipped_steps,
        transform_notes=checkpoint.transform_notes,
    )
    (run_dir / "report.md").write_text(outcome.report_md, encoding="utf-8")
    checkpoint.stats["lint_issues_before"] = outcome.lint_before
    checkpoint.stats["lint_issues_after"] = outcome.lint_after
    checkpoint.stats["lint_issues"] = outcome.lint_after
    store.save_checkpoint(checkpoint)
    return outcome
