"""One-shot report writer plus the citation lint gate."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from research_agent.evidence.ledger import Ledger, _atomic_write_text
from research_agent.llm import LLMClient, LLMError
from research_agent.runbook import Runbook

if TYPE_CHECKING:
    from research_agent.agent.citations import FidelityResult

log = logging.getLogger(__name__)

_CITATION_BLOCK_RE = re.compile(r"\[[^\]]*?\bC\d+[^\]]*?\]")
_CITATION_ID_RE = re.compile(r"C(\d+)")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_NUMBER_RE = re.compile(
    r"(?<![\w\d-])(?:[$€£]\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?%|\d{1,3}(?:,\d{3})+(?:\.\d+)?"
    r"|\d+(?:\.\d+)?\s?(?:k|K|M|B)\b"
    r"|\d[\d,]*(?:\.\d+)?\s+(?:monthly\s+)?(?:visitors|visits|users|downloads|installs|reviews"
    r"|keywords|backlinks|referring\s+domains|ads|creatives|employees|jobs|queries|mentions"
    r"|revenue|traffic|searches|impressions|clicks))"
)
_YEAR_PREFIX_RE = re.compile(r"(?:^|\b(?:in|on|of|from|by|year)\s+)$", re.IGNORECASE)
_BARE_ID_RE = re.compile(r"\bC(\d+)\b")
_CONFLICT_REGISTER_RE = re.compile(r"^\s*-\s*C\d+\b|\bvs\s+C\d+\b")
_SOURCE_LOG_ROW_RE = re.compile(r"^\s*\|\s*C\d+\s*\|.*$", re.MULTILINE)
_ASSUMPTION_MARKER = "(target, assumption — not data)"
_UNVERIFIED_MARKER = "[UNVERIFIED"
_MAX_REPAIR_PASSES = 3

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
- Derived numbers: a computed figure (ratio, average, per-month cadence, total)
  is allowed ONLY when the same sentence carries the [C..] refs of EVERY input
  figure plus the word "derived".
  RIGHT: "Engagement is 3.4% (derived: 113K views [C7] / 3.3M followers [C9])."
- Assumed targets: a KPI target, benchmark, or illustrative goal must be marked
  "(target, assumption — not data)" and must not be dressed up as a measured
  figure. RIGHT: "Aim for 5%+ CTR (target, assumption — not data)."
- If a number fits none of these rules, it does not go in the report.

## Charts (OPTIONAL, max 3 per report)
For genuinely comparative numeric series that exist in the ledger you may embed
up to 3 chart directives as fenced blocks — nothing else charts, and prose must
never describe a chart instead:
```chart {{"type": "bar"|"line", "title": "...", "labels": ["..."], "values": [<numbers>], "claim_refs": ["C1", "C2"]}}
```
Every value must come from the referenced claims — the renderer rejects charts
whose values are not in the ledger.

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
- For each uncited number choose EXACTLY ONE action:
  (a) attach the correct [C..] ref IMMEDIATELY after the figure — but ONLY if
      the ledger claim's subject matches what the sentence states (check the
      subject; citing a claim about a different entity is worse than not citing);
  (b) rewrite it as a derivation — same sentence, [C..] refs for EVERY input
      figure, plus the word "derived";
  (c) mark it as an assumption with the exact marker
      "(target, assumption — not data)";
  (d) delete it;
  (e) mark it [UNVERIFIED] — when the figure is worth keeping visible but no
      ledger claim backs it.
  Never leave a bare number behind, and NEVER invent a citation to cover one.
- For each missing_ref (a [C..] that does not exist in the ledger): replace it
  with the correct claim id, or handle the figure per the actions above.
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
    repair_passes: int = 0


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


def _sentence_at(text: str, position: int) -> str:
    """The sentence containing ``position`` — citations cover a figure only
    inside the same sentence; a neighbour sentence's [C..] is not support."""
    line_start = text.rfind("\n", 0, position) + 1
    line_end = text.find("\n", position)
    if line_end < 0:
        line_end = len(text)
    line = text[line_start:line_end]
    rel = position - line_start
    cursor = 0
    for sentence in _SENTENCE_SPLIT_RE.split(line):
        idx = line.find(sentence, cursor)
        if idx < 0:
            continue
        cursor = idx + len(sentence)
        if idx <= rel < idx + len(sentence):
            return sentence
    return line


def _looks_like_year(scan_text: str, match: re.Match[str]) -> bool:
    """A bare 4-digit 1900-2099 number after 'in/of/…' is a year, not a metric —
    flagging it makes repair delete legitimate prose."""
    digits = match.group(0).split(" ")[0].rstrip("%")
    if not (digits.isdigit() and len(digits) == 4 and 1900 <= int(digits) <= 2099):
        return False
    prefix = scan_text[:match.start()].rstrip()
    last_nl = prefix.rfind("\n")
    prefix = prefix[last_nl + 1:]
    return bool(_YEAR_PREFIX_RE.search(prefix + " "))


def lint_report(report_md: str, ledger: Ledger) -> LintResult:
    result = LintResult()
    known_ids = {c.id for c in ledger.claims}

    cited: list[str] = []
    for block in _CITATION_BLOCK_RE.findall(report_md):
        # An [UNVERIFIED: ...] label can quote a bare C<n> from the sentence it
        # replaced — it is a tombstone, not a citation, and must not raise a
        # phantom missing_ref.
        if block.startswith(_UNVERIFIED_MARKER):
            continue
        cited.extend(f"C{n}" for n in _CITATION_ID_RE.findall(block))
    for ref in dict.fromkeys(cited):
        if ref not in known_ids:
            result.issues.append(
                LintIssue(
                    kind="missing_ref",
                    text=ref,
                    detail=f"citation [{ref}] does not exist in the ledger",
                )
            )

    scan_text = _SOURCE_LOG_ROW_RE.sub("", report_md)
    for match in _NUMBER_RE.finditer(scan_text):
        if _looks_like_year(scan_text, match):
            continue
        sentence = _sentence_at(scan_text, match.start())
        # A bare claim id that exists in the ledger (the conflict register's
        # "C41 vs C126" style) is a traceable reference — unbracketed, but not
        # uncited. Unknown bare ids stay prose and never cover a figure. The
        # exemption is confined to conflict-register rows (a "- C…" bullet or a
        # "… vs C…" pairing); a bare id in ordinary prose covers nothing.
        bare_refs = (f"C{n}" for n in _BARE_ID_RE.findall(sentence))
        if (
            _CITATION_BLOCK_RE.search(sentence)
            or _ASSUMPTION_MARKER in sentence
            or _UNVERIFIED_MARKER in sentence
            or (
                _CONFLICT_REGISTER_RE.search(sentence)
                and any(ref in known_ids for ref in bare_refs)
            )
        ):
            continue
        result.issues.append(
                LintIssue(
                    kind="uncited_number",
                    text=match.group(0).strip(),
                    detail="numeric claim without a [C..] citation in its sentence",
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
    lint_current = lint_report(draft, ledger)
    lint_before = len(lint_current.issues)
    if not lint_current.issues:
        return WriterOutcome(
            report_md=draft, lint_before=0, lint_after=0, revised=False
        )
    log.info("writer draft failed lint (%d issues); running repair passes", lint_before)

    report = draft
    previous_keys = _issue_keys(lint_current)
    passes = 0
    for pass_no in range(1, _MAX_REPAIR_PASSES + 1):
        try:
            repaired = await repair_report(llm, report, lint_current, ledger)
        except LLMError as exc:
            if exc.retryable:
                raise
            # A truncated repair (finish_reason='length') is no better than
            # the draft it started from — keep the draft and the run's
            # evidence instead of dying with both.
            log.warning(
                "repair pass %d failed non-retryably (%s); keeping the previous draft",
                pass_no, exc,
            )
            break
        passes = pass_no
        if _repair_collapsed(repaired, report):
            # An empty or gutted repair lints trivially clean — shipping it
            # would turn a failed pass into a silent success.
            log.warning(
                "repair pass %d returned a collapsed report (%d chars); "
                "keeping the previous draft",
                pass_no, len(repaired.strip()),
            )
            break
        report = repaired
        lint_current = lint_report(report, ledger)
        keys = _issue_keys(lint_current)
        log.info("repair pass %d: %d -> %d lint issues", pass_no, len(previous_keys), len(keys))
        if not keys:
            break
        if keys == previous_keys:
            # Same (kind, text) set twice: the repair is going in circles.
            # A smaller but DIFFERENT set means it fixed some and broke others —
            # that is progress worth another pass, not a stop signal.
            log.warning("repair pass %d produced an identical issue set; stopping", pass_no)
            break
        previous_keys = keys

    # A dangling [C99] the repair could not resolve is unverifiable by
    # construction — mark it instead of shipping a phantom citation.
    if lint_current.missing_refs:
        report = sweep_missing_refs(report, lint_current.missing_refs)
        lint_current = lint_report(report, ledger)
        log.info("missing_ref sweep: %d issue(s) remain", len(lint_current.issues))

    return WriterOutcome(
        report_md=report,
        lint_before=lint_before,
        lint_after=len(lint_current.issues),
        revised=True,
        repair_passes=passes,
    )


def _issue_keys(lint: LintResult) -> set[tuple[str, str]]:
    return {(issue.kind, issue.text) for issue in lint.issues}


def _repair_collapsed(repaired: str, previous: str) -> bool:
    # Both conditions: a repair that merely shrinks the report can be legit
    # (deleting bare numbers is an allowed action), but an output that is at
    # once tiny (<40 chars) and a major shrink (<50% of the draft) — or
    # empty/whitespace outright — is a failed pass, not a clean report.
    stripped = repaired.strip()
    return not stripped or (
        len(stripped) < 40 and len(stripped) < 0.5 * len(previous.strip())
    )


def sweep_missing_refs(report_md: str, missing_refs: list[str]) -> str:
    """Mark citations whose claim id does not exist as [UNVERIFIED]."""
    out = report_md
    for ref in missing_refs:
        out = out.replace(f"[{ref}]", "[UNVERIFIED]")
        out = re.sub(rf"\b{re.escape(ref)}\b", "UNVERIFIED", out)
    return out


async def produce_report(
    llm: LLMClient,
    runbook: Runbook,
    ledger: Ledger,
    brief: dict[str, Any],
    *,
    partial: bool = False,
    skipped_steps: list[dict[str, Any]] | None = None,
    transform_notes: list[str] | None = None,
) -> tuple[WriterOutcome, "FidelityResult"]:
    from research_agent.agent.citations import verify_citations

    outcome = await write_and_repair(
        llm, runbook, ledger, brief,
        partial=partial, skipped_steps=skipped_steps, transform_notes=transform_notes,
    )
    fidelity = await verify_citations(llm, outcome.report_md, ledger)
    if fidelity.unverified:
        outcome = outcome.model_copy(update={"report_md": fidelity.report_md})
    # lint_after must describe the text that actually ships — fidelity rewrites
    # are lint-safe by design, but a stale pre-fidelity count is how a dangling
    # ref once reached a final report.
    final_lint = lint_report(outcome.report_md, ledger)
    outcome = outcome.model_copy(update={"lint_after": len(final_lint.issues)})
    return outcome, fidelity


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
    outcome, fidelity = await produce_report(
        llm, runbook, ledger, checkpoint.brief,
        partial=checkpoint.partial,
        skipped_steps=checkpoint.skipped_steps,
        transform_notes=checkpoint.transform_notes,
    )
    _atomic_write_text(run_dir / "report.md", outcome.report_md)
    checkpoint.stats["lint_issues_before"] = outcome.lint_before
    checkpoint.stats["lint_issues_after"] = outcome.lint_after
    checkpoint.stats["lint_issues"] = outcome.lint_after
    checkpoint.stats["citation_fidelity"] = fidelity.stats
    store.save_checkpoint(checkpoint)
    return outcome
