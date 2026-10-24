"""One-shot report writer plus the citation lint gate."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from research_agent.agent import tool_limits
from research_agent.evidence.ledger import Ledger, _atomic_write_text
from research_agent.llm import LLMBudgetExceeded, LLMClient, LLMError
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
#: A citation bracket holding the writer's own hesitation ("[C186? no, [C237]]"):
#: a question mark or a nested bracket inside it is drafting residue (B-068).
_MALFORMED_CITATION_RE = re.compile(r"\[C\d+[^\]\[\n]*?[?\[][^\n]*?\]")
_CONFLICT_REGISTER_RE = re.compile(r"^\s*-\s*C\d+\b|\bvs\s+C\d+\b")
_SOURCE_LOG_ROW_RE = re.compile(r"^\s*\|\s*C\d+\s*\|.*$", re.MULTILINE)
_ASSUMPTION_MARKER = "(target, assumption — not data)"
_UNVERIFIED_MARKER = "[UNVERIFIED"
_MAX_REPAIR_PASSES = 3
_DRAFT_MAX_TOKENS = 8000
#: B-052: a 44-step finance report on xiaomi/mimo-v2.6-pro (16,258 tokens in) was cut
#: at both 8000 and 12000; the second budget matches the planner's escalation.
_DRAFT_ESCALATED_MAX_TOKENS = 24_000
#: A repair pass returns only the lines it fixes (B-059), so it needs far less
#: than a draft; a model that rewrites the whole report anyway is cut here and
#: the draft is kept.
_REPAIR_MAX_TOKENS = 8_000

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
- Estimates must carry their error band and a VERIFIED, ASSUMED or CONFLICT tag
  matching the ledger claim status. VERIFIED means the claim's quote was found in
  the stored source (verification "span") or two independent sources agree
  ("corroboration") — never call a claim VERIFIED that the ledger marks otherwise.
  A claim with status "conflict" is cited with its disagreeing peers and
  [CONFLICT]; never present one side as settled, and never chart it.
  verification "span" means the one source literally says it: where a runbook
  rule requires two independent sources for a figure, a span-verified claim
  satisfies one of them — tag it "VERIFIED (single source)".
- If the ledger has no evidence for a section, say so explicitly; do not fill gaps
  from general knowledge.
{partial_note}
Write the report now, in markdown."""


REPAIR_SYSTEM_TEMPLATE = """\
You are the citation-repair pass for a research report. Lines of the report
failed citation lint; fix EVERY listed issue on its line.

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
- For each malformed_citation (a bracket with a question mark, a note or a
  nested bracket inside it): replace it with plain [C..] refs that support the
  sentence; no commentary inside a citation.
- Where two ledger claims conflict on the same subject, cite BOTH with
  [CONFLICT].
- For status_mislabel, conflict_hidden, quote_not_in_ledger and value_mismatch,
  do what the issue's detail says, on that line only; never add a claim id the
  ledger does not hold.
- Change nothing else on the line: wording that is already correct stays.

## Evidence ledger (the ONLY source of valid claim ids)
{ledger_json}

Output only the fixed lines in the format the request gives."""


class WriterOutcome(BaseModel):
    report_md: str
    lint_before: int
    lint_after: int
    revised: bool
    repair_passes: int = 0


class RewriteError(Exception):
    pass


def report_head(report_md: str) -> str:
    """The part of a report a reader meets before any finding: the title and
    the preamble up to the first `## ` section."""
    lines = report_md.splitlines()
    cut = next((i for i, line in enumerate(lines[1:], 1) if line.startswith("## ")), len(lines))
    return "\n".join(lines[:cut])


def partial_disclosed(report_md: str) -> bool:
    """A partial run's report says so before its first section — the rule the
    judge vetoes on (evals/judge.py) and the orchestrator enforces."""
    return re.search(r"\bpartial(?:ly)?\b", report_head(report_md), re.IGNORECASE) is not None


def disclose_partial(report_md: str, reason: str | None) -> str:
    """Make a partial run's report say so: the writer is told only when the run
    was partial before it wrote; a run that turns partial afterwards (a refused
    repair or citation pass, a kept report) gets this deterministic line."""
    if partial_disclosed(report_md):
        return report_md
    lines = report_md.splitlines()
    title, rest = (lines[0], lines[1:]) if lines and lines[0].startswith("# ") else ("", lines)
    note = f"**PARTIAL RUN:** {reason or 'the run stopped before completing every planned step'}."
    return "\n".join(([title, ""] if title else []) + [note, ""] + rest) + ("\n" if report_md.endswith("\n") else "")


def ledger_only_report(runbook: Runbook, ledger: Ledger, reason: str,
                       coverage_statements: list[str] | None = None) -> WriterOutcome:
    """The report when no LLM budget is left for the writer: the evidence as
    gathered, every claim with its status and source — nothing synthesized.

    A person reads this listing, so its source coverage is each limit's
    `statement` (tool_limits.statements), never the writer's instruction (B-077)."""
    lines = [
        f"# {runbook.meta.name} — PARTIAL: evidence only",
        "",
        f"The LLM budget ran out before the report could be written ({reason}). "
        "Below is the evidence ledger as gathered; no synthesis, no conclusions. "
        "`prowl-research rewrite <run_id> --max-llm-usd <larger>` writes the full "
        "report under a larger cap (its LLM calls count against the run).",
        "",
        "| Claim | Value | Status | Source |",
        "|---|---|---|---|",
    ]
    for c in ledger.claims:
        value = "" if c.value is None else f"{c.value}{(' ' + c.unit) if c.unit else ''}"
        text = c.claim.replace("|", "/").replace("\n", " ")
        lines.append(f"| {text} [{c.id}] | {value} | {c.status.value} | {c.source_tool} |")
    if not ledger.claims:
        lines.append("| (no evidence gathered) | | | |")
    if coverage_statements:
        lines += ["", "Source coverage:", *(f"- {note}" for note in coverage_statements)]
    return WriterOutcome(report_md="\n".join(lines) + "\n", lint_before=0, lint_after=0, revised=False)


class LintIssue(BaseModel):
    kind: str
    text: str
    detail: str
    #: The sentence the issue sits in, so the repair pass can find its line (B-059).
    context: str = ""


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

    for match in _MALFORMED_CITATION_RE.finditer(report_md):
        result.issues.append(
            LintIssue(
                kind="malformed_citation",
                text=match.group(0)[:120],
                detail="drafting residue inside a citation; keep only the claim ids that support the sentence",
                context=match.group(0),
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
                    context=sentence,
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
    coverage_notes: list[str] | None = None,
) -> str:
    partial_note = ""
    if partial:
        steps = skipped_steps or []
        # A refusal is a data step the source answered without data (B-049); a lost
        # raw or a failed transform is not one, and a pending or budget-skipped step
        # did not run. Everything else is named with its state.
        refused = [s for s in steps if s.get("state") in ("failed", "skipped_on_error")
                   and s.get("tool") != "transform" and not str(s.get("reason") or "").startswith("raw_write")]
        # A step whose arguments held no value was never sent (B-065, B-070, B-071): the
        # plan's gap, not the source's answer, so the report must not blame the source.
        not_sent = [s for s in refused if "not sent:" in str(s.get("reason") or "")]
        refused = [s for s in refused if s not in not_sent]
        not_run = [s for s in steps if s.get("state") in ("pending", "skipped_budget")]
        other = [s for s in steps if s not in refused and s not in not_sent and s not in not_run]
        lines = ["\n## PARTIAL RUN",
                 "Mark the report as partial in its first line and list the sections that are missing or thin."]
        if refused:
            # B-049: the run went on past these; their answer was a refusal, not data.
            lines.append("These steps were refused by the data source (no data from them; say so, never fill "
                         "the gap from elsewhere): "
                         + "; ".join(f"{s.get('step', '?')}: {str(s.get('reason') or '')[:200]}" for s in refused) + ".")
        if not_sent:
            lines.append("These steps were not sent: the plan had no usable value for an argument, so the data "
                         "source was never asked (no data from them; say so as a gap of this run, not as the "
                         "source's answer, and never fill it from elsewhere): "
                         + "; ".join(f"{s.get('step', '?')}: {str(s.get('reason') or '')[:200]}" for s in not_sent) + ".")
        if not_run:
            lines.append("These steps did not run (the run stopped before them): "
                         + ", ".join(s.get("step", "?") for s in not_run) + ".")
        if other:
            lines.append("These steps did not complete: "
                         + "; ".join(f"{s.get('step', '?')} ({s.get('state', '?')}): "
                                     f"{str(s.get('reason') or '')[:160]}" for s in other) + ".")
        if not steps:
            lines.append("Skipped steps: none.")
        partial_note = "\n".join(lines) + "\n"
    else:
        # A complete run can still hold an optional step that was never sent (every
        # runbook calls tiktok_ads_library as optional): the report says so rather than
        # letting the missing source read as a finding.
        not_sent = [s for s in (skipped_steps or []) if "not sent:" in str(s.get("reason") or "")]
        if not_sent:
            partial_note = ("\n## STEPS NOT SENT\nThese optional steps were not sent: the plan had no usable value "
                            "for an argument, so the data source was never asked. Name each as a gap of this run "
                            "where its section would use it (never as the source's answer, never as a finding such "
                            "as a channel the subject does not use): "
                            + "; ".join(f"{s.get('step', '?')}: {str(s.get('reason') or '')[:200]}" for s in not_sent)
                            + ".\n")

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
    if coverage_notes:
        # B-071: the writer never sees step arguments, so what a limited source covers is told here.
        user += "\n\n## Source coverage (state it wherever these results are used)\n" + "\n".join(
            f"- {note}" for note in coverage_notes)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        return await llm.complete(
            messages, tier="strong", max_tokens=_DRAFT_MAX_TOKENS, temperature=0.3, stage="writer",
        )
    except LLMError as exc:
        if exc.retryable or exc.finish_reason != "length":
            raise
        first_truncated = (exc.content or "").strip()
        # A truncated first draft arrives after the run's entire tool spend —
        # dying here loses the ledger and the money. Retry once with a larger
        # output budget before giving up on the report.
        log.warning(
            "writer draft truncated at max_tokens=%d; retrying with max_tokens=%d",
            _DRAFT_MAX_TOKENS, _DRAFT_ESCALATED_MAX_TOKENS,
        )
    try:
        return await llm.complete(
            messages, tier="strong", max_tokens=_DRAFT_ESCALATED_MAX_TOKENS, temperature=0.3,
            stage="writer",
        )
    except LLMBudgetExceeded:
        if not first_truncated:
            raise
        # The cap refuses the larger retry: the first draft was paid for —
        # ship it truncated rather than drop it for the ledger listing. The
        # run records the refusal (budget_llm).
        return first_truncated + "\n\n*(Report truncated: the LLM budget did not allow a longer draft.)*"
    except LLMError as exc:
        truncated = (exc.content or "").strip()
        if exc.retryable or exc.finish_reason != "length" or not truncated:
            raise
        # Still truncated at the ceiling: ship the partial draft (lint and
        # repair can only improve it) rather than lose the run's evidence.
        log.warning(
            "writer draft still truncated at max_tokens=%d; shipping the partial draft",
            _DRAFT_ESCALATED_MAX_TOKENS,
        )
        return truncated + "\n\n*(Report truncated at the model's output limit.)*"


_REPAIR_MAX_LINES = 60
_PATCH_RE = re.compile(r"^L(\d+):[ \t]?(.*)$", re.MULTILINE)


def _issue_line(lines: list[str], issue: LintIssue) -> int | None:
    """The report line an issue sits on, or None when it cannot be found."""
    if issue.kind == "missing_ref":
        pattern = re.compile(rf"\[[^\]]*\b{re.escape(issue.text)}\b[^\]]*\]")
        return next((i for i, line in enumerate(lines) if pattern.search(line)), None)
    probe = " ".join((issue.context or issue.text).split())[:60]
    if not probe:
        return None
    return next((i for i, line in enumerate(lines) if probe in " ".join(line.split())), None)


async def repair_report(
    llm: LLMClient,
    draft: str,
    lint: LintResult,
    ledger: Ledger,
) -> str:
    """One repair pass, by line (B-059): the lines carrying issues go to the model
    with their issues, and it returns only those lines, which are patched in.
    A whole-report rewrite was cut at 24000 tokens on a long report and thrown
    away. A model that answers with a whole report anyway is taken as before."""
    lines = draft.split("\n")
    by_line: dict[int, list[LintIssue]] = {}
    for issue in lint.issues:
        index = _issue_line(lines, issue)
        if index is not None:
            by_line.setdefault(index, []).append(issue)
    if not by_line:
        return draft
    chosen = sorted(by_line)[:_REPAIR_MAX_LINES]
    tasks = "\n\n".join(
        f"L{i}: {lines[i]}\n" + "\n".join(f"  - {issue.kind}: {issue.text!r} ({issue.detail})" for issue in by_line[i])
        for i in chosen
    )
    system = REPAIR_SYSTEM_TEMPLATE.format(ledger_json=ledger.as_prompt_json())
    user = (f"## Lines to fix\n{tasks}\n\n"
            "Return ONLY the fixed lines, one per line given, each as `L<n>: <fixed line>` with the same n. "
            "An empty fixed line deletes it. Do not return any other text.")
    answer = await llm.complete(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        tier="strong",
        max_tokens=_REPAIR_MAX_TOKENS,
        temperature=0.2,
        stage="repair",
        # B-062, measured on accept-finance-20261021: with reasoning on, mimo spent all
        # 8000 output tokens reasoning and returned nothing; off, the same request
        # returned 37 line patches in 2633 tokens.
        reasoning=False,
    )
    patches = {int(n): text for n, text in _PATCH_RE.findall(answer) if int(n) in by_line}
    if not patches:
        # No line patches: the model rewrote the whole report. Take it as before;
        # the caller's collapse check refuses a gutted answer.
        return answer
    patched = [patches.get(i, line) for i, line in enumerate(lines)]
    return "\n".join(line for i, line in enumerate(patched) if not (i in patches and not line.strip()))


#: How the repair pass fixes each defect the judge would veto on (B-057).
_DEFECT_FIX = {
    "status_mislabel": "the ledger does not hold this claim as verified: drop the VERIFIED tag or say ASSUMED/UNVERIFIED as the ledger does",
    "conflict_hidden": "the cited claim is in CONFLICT in the ledger: tag it [CONFLICT] on this line and show both readings",
    "quote_not_in_ledger": "no cited claim holds this quotation: cite the claim that does, or paraphrase without quotation marks",
    "value_mismatch": "no cited claim carries this figure: use the claim's value, cite the claim that has it, or mark the figure derived",
}


def _writing_lint(report_md: str, ledger: Ledger) -> LintResult:
    """The writer lint plus the defects the judge proves by code (B-057), so the
    repair pass fixes them before the report ships. missing_ref is lint's own;
    an undisclosed partial run is handled by disclose_partial."""
    from research_agent.agent.report_checks import code_defects  # imports this module

    result = lint_report(report_md, ledger)
    for defect in code_defects(report_md, ledger):
        if defect["kind"] in _DEFECT_FIX:
            result.issues.append(LintIssue(kind=defect["kind"], text=defect["text"],
                                           detail=f"[{defect['claim']}] {_DEFECT_FIX[defect['kind']]}",
                                           context=defect["text"]))
    return result


async def write_and_repair(
    llm: LLMClient,
    runbook: Runbook,
    ledger: Ledger,
    brief: dict[str, Any],
    *,
    partial: bool = False,
    skipped_steps: list[dict[str, Any]] | None = None,
    transform_notes: list[str] | None = None,
    coverage_notes: list[str] | None = None,
) -> WriterOutcome:
    draft = await write_report(
        llm, runbook, ledger, brief,
        partial=partial, skipped_steps=skipped_steps, transform_notes=transform_notes,
        coverage_notes=coverage_notes,
    )
    lint_current = _writing_lint(draft, ledger)
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
        lint_current = _writing_lint(report, ledger)
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
        lint_current = _writing_lint(report, ledger)
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
    coverage_notes: list[str] | None = None,
) -> tuple[WriterOutcome, "FidelityResult"]:
    from research_agent.agent.citations import verify_citations

    outcome = await write_and_repair(
        llm, runbook, ledger, brief,
        partial=partial, skipped_steps=skipped_steps, transform_notes=transform_notes,
        coverage_notes=coverage_notes,
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
    llm: LLMClient, runs_root: Path, run_id: str, *, max_llm_usd: float | None = None
) -> WriterOutcome:
    """Re-run only the writer over a finished run's ledger.

    Takes the run lock first: a run that is live in any process is its own
    owner's to write, so a held lock is a typed refusal with no write. The
    lock is held for the whole rewrite, so a run cannot start under it."""
    from research_agent.evidence.runlock import RunLock

    run_dir = Path(runs_root) / run_id
    if not run_dir.is_dir():
        raise RewriteError(f"run '{run_id}' has no checkpoint at {run_dir}")
    lock = RunLock(run_dir)
    if not lock.acquire(blocking=False):
        # Lazy: the orchestrator imports this module at load time.
        from research_agent.agent.orchestrator import OrchestratorError
        from research_agent.events import emit

        emit(log, "run.rewrite.refused", logging.WARNING, run_id=run_id)
        raise OrchestratorError(f"run {run_id} is active; rewrite refused")
    try:
        return await _rewrite_locked(llm, run_dir, run_id, max_llm_usd)
    finally:
        lock.release()


async def _rewrite_locked(llm: LLMClient, run_dir: Path, run_id: str,
                          max_llm_usd: float | None = None) -> WriterOutcome:
    from research_agent.evidence.store import ArtifactStore
    from research_agent.runbook import get_runbook

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
    ledger.run_id = run_id
    runbook = get_runbook(checkpoint.runbook)
    from research_agent.agent.metering import attach_run_meter, budget_stats

    # A rewrite spends the run's own LLM money: same cap, same attempt ledger.
    meter = attach_run_meter(llm, checkpoint, store, runbook.meta.budget.max_llm_usd, max_llm_usd)
    store.save_checkpoint(checkpoint)
    try:
        outcome, fidelity = await produce_report(
            llm, runbook, ledger, checkpoint.brief,
            partial=checkpoint.partial,
            skipped_steps=checkpoint.skipped_steps,
            transform_notes=checkpoint.transform_notes,
            coverage_notes=tool_limits.coverage_notes(s.tool for s in checkpoint.steps if s.state == "completed"),
        )
    except LLMBudgetExceeded as exc:
        checkpoint.stats["llm_budget"] = budget_stats(meter, checkpoint)
        store.save_checkpoint(checkpoint)
        raise RewriteError(
            f"run '{run_id}': the LLM budget does not allow a rewrite ({exc}); "
            "the existing report is unchanged — pass a larger --max-llm-usd") from exc
    finally:
        llm.meter = None
    # The report was written against the recomputed statuses (a v1 ledger is
    # upgraded on load): the file the report cites must say the same.
    ledger.save()
    report_md = disclose_partial(outcome.report_md, checkpoint.stop_reason) if checkpoint.partial else outcome.report_md
    _atomic_write_text(run_dir / "report.md", report_md)
    checkpoint.stats["lint_issues_before"] = outcome.lint_before
    checkpoint.stats["lint_issues_after"] = outcome.lint_after
    checkpoint.stats["lint_issues"] = outcome.lint_after
    checkpoint.stats["citation_fidelity"] = fidelity.stats
    checkpoint.stats["llm_budget"] = budget_stats(meter, checkpoint)
    checkpoint.stats["rewritten_at"] = datetime.now(timezone.utc).isoformat()
    store.save_checkpoint(checkpoint)
    try:
        from research_agent.report.render import render_run

        render_run(run_dir)
    except Exception as exc:
        log.warning("HTML export failed for %s: %s", run_dir, exc)
    return outcome
