#!/usr/bin/env python3
"""LLM judge for a finished run: 5-dimension quality rubric.

Usage: python evals/judge.py --run runs/<id> [--threshold 0.7] [--max-usd 0.50]

Programmatic signals (lint output, ledger stats, section coverage, budget
counters) are computed in code and injected into the judge prompt — the LLM
never sees a number the code did not produce. Three dimensions are capped by
code (citations by the lint, completeness by section coverage, source quality
by the primary-source share), and a defect the code proves (`code_defects`:
an invented citation or quotation, a figure its claim does not carry, a hidden
conflict, an undisclosed partial run) vetoes the pass whatever the model scored
(W6-T1, KA-G02): a lenient model cannot talk a planted defect into a PASS.

The judge's own LLM calls are metered (B-041): each attempt is checked against
`max_usd` before it is sent and recorded in `<run>/judge-ledger.json` — never
in the run's checkpoint. Exit codes: 0 pass, 1 fail, 2 judge error (including
a refusal by the judge's own ceiling), so a judge failure never reads as FAIL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from research_agent.agent.writer import (  # noqa: E402
    _CITATION_BLOCK_RE, _CITATION_ID_RE, _NUMBER_RE, lint_report, partial_disclosed,
)
from research_agent.evidence.ledger import Ledger  # noqa: E402
from research_agent.evidence.source import is_llm_answer, is_transform  # noqa: E402
from research_agent.evidence.store import ArtifactStore, Checkpoint  # noqa: E402
from research_agent.evidence.store import AttemptRecord, CheckpointWriteError  # noqa: E402
from research_agent.llm import LLMBudgetExceeded, LLMClient, LLMError, LlmMeter  # noqa: E402
from research_agent.runbook import Runbook, get_runbook  # noqa: E402

log = logging.getLogger(__name__)

DIMENSIONS = (
    "factual_accuracy",
    "citation_accuracy",
    "completeness",
    "source_quality",
    "tool_efficiency",
)
WEIGHTS = {
    "factual_accuracy": 0.30,
    "citation_accuracy": 0.25,
    "completeness": 0.20,
    "source_quality": 0.15,
    "tool_efficiency": 0.10,
}
DEFAULT_THRESHOLD = 0.7
#: The judge's own LLM ceiling per judging, USD (B-041).
DEFAULT_JUDGE_MAX_USD = 0.50
EXIT_PASS, EXIT_FAIL, EXIT_ERROR = 0, 1, 2
JUDGE_LEDGER = "judge-ledger.json"

#: One definition of an LLM-derived source, shared with the ledger's
#: independence rules (research_agent.evidence.source): LLM-answer tools and
#: transforms are never primary sources.
def _llm_derived(tool: str) -> bool:
    return is_llm_answer(tool) or is_transform(tool)


_REPORT_SNIPPET_CHARS = 20_000
_SECTION_RE = re.compile(r"^\s*\d+\.\s+\*\*([^*]+)\*\*", re.MULTILINE)


class JudgeError(Exception):
    pass


class JudgeResult:
    def __init__(
        self,
        scores: dict[str, float],
        reasons: dict[str, str],
        signals: dict[str, Any],
        threshold: float,
    ) -> None:
        self.scores = scores
        self.reasons = reasons
        self.signals = signals
        self.threshold = threshold
        self.total = round(sum(WEIGHTS[d] * scores[d] for d in DIMENSIONS), 4)
        #: Code-proven defects: each one vetoes the pass (see code_defects).
        self.defects: list[dict[str, str]] = list(signals.get("defects") or [])
        self.passed = self.total >= threshold and not self.defects
        #: What this judging spent on its own LLM calls (None: unmetered).
        self.spend_usd: float | None = None


def load_run(run_dir: Path, runbooks_dir: Path | None = None) -> tuple[str, Ledger, Checkpoint, Runbook]:
    report_path = run_dir / "report.md"
    checkpoint_path = run_dir / "checkpoint.json"
    ledger_path = run_dir / "ledger.json"
    if not report_path.is_file():
        raise JudgeError(f"{run_dir}: no report.md — run has not produced a report")
    if not checkpoint_path.is_file():
        raise JudgeError(f"{run_dir}: no checkpoint.json — cannot identify the runbook")
    report_md = report_path.read_text(encoding="utf-8")
    if not report_md.strip():
        # An empty report lints clean (no numbers to flag), which would hand
        # the citation cap to a document that says nothing.
        raise JudgeError(f"{run_dir}: report.md is empty — nothing to judge")
    if not ledger_path.is_file():
        raise JudgeError(f"{run_dir}: no ledger.json — the run's evidence is missing")
    ledger = Ledger.load(ledger_path)
    try:
        # Through the store: a version-1 run is migrated, not read as empty.
        checkpoint = ArtifactStore(run_dir).load_checkpoint()
    except ValueError as exc:
        raise JudgeError(f"{run_dir}: {exc}") from exc
    runbook = get_runbook(checkpoint.runbook, runbooks_dir)
    return report_md, ledger, checkpoint, runbook


def required_sections(runbook: Runbook) -> list[str]:
    return [m.strip() for m in _SECTION_RE.findall(runbook.output_instructions)]


def section_coverage(report_md: str, sections: list[str]) -> dict[str, Any]:
    report_lower = report_md.lower()
    covered, missing = [], []
    for section in sections:
        words = [w for w in re.findall(r"[a-z0-9]+", section.lower()) if len(w) > 3]
        hits = sum(1 for w in words if w in report_lower)
        (covered if words and hits / len(words) >= 0.5 else missing).append(section)
    return {"required": sections, "covered": covered, "missing": missing}


def ledger_stats(ledger: Ledger) -> dict[str, Any]:
    claims = ledger.claims
    llm_derived = [
        c.id for c in claims if _llm_derived(c.source_tool)
    ]
    by_status: dict[str, int] = {}
    by_method: dict[str, int] = {}
    for claim in claims:
        by_status[claim.status.value] = by_status.get(claim.status.value, 0) + 1
        method = claim.verification.get("method", "none")
        by_method[method] = by_method.get(method, 0) + 1
    return {
        "claims": len(claims),
        "by_status": by_status,
        "by_verification": by_method,
        "llm_derived_claims": llm_derived,
        "primary_source_ratio": (
            round((len(claims) - len(llm_derived)) / len(claims), 3) if claims else None
        ),
    }


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(\[])")
_QUOTE_RE = re.compile(r"[\"“]([^\"”]{3,})[\"”]")
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_LEADING_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_SCALE_WORD_RE = re.compile(r"\s*(thousand|million|billion|bn)\b|([kKMB])\b", re.IGNORECASE)
#: "1.5 million visits": a scale word between the number and its unit, which
#: the writer lint's _NUMBER_RE does not read as one figure.
_SCALED_RE = re.compile(r"(?<![\w\d-])[$€£]?\s?\d[\d,]*(?:\.\d+)?\s*(?:thousand|million|billion|bn)\b", re.IGNORECASE)
_LETTER_SCALE = {"k": 1e3, "m": 1e6, "b": 1e9}
_SCALE = {"k": 1e3, "K": 1e3, "thousand": 1e3, "M": 1e6, "million": 1e6, "B": 1e9, "bn": 1e9, "billion": 1e9}


_ABBREVIATION_RE = re.compile(r"\b(?:vs|e\.g|i\.e|approx|etc|cf|ca|incl|est)\.$", re.IGNORECASE)
#: A quoted search phrase is a keyword, not a quotation of a source.
_KEYWORD_CONTEXT_RE = re.compile(r"\b(?:keywords?|search(?:es)?|quer(?:y|ies)|terms?|phrases?|SERP)\b", re.IGNORECASE)


def _split_line(line: str) -> list[str]:
    parts: list[str] = []
    for chunk in _SENTENCE_RE.split(line):
        if parts and _ABBREVIATION_RE.search(parts[-1]):
            parts[-1] += " " + chunk  # "300 vs. 900": one sentence
        else:
            parts.append(chunk)
    return [p for p in parts if p.strip()]


def _sentences(report_md: str) -> list[str]:
    out: list[str] = []
    for line in report_md.splitlines():
        out.extend(_split_line(line))
    return out


def _cited(sentence: str) -> list[str]:
    """Claim ids a sentence cites. An `[UNVERIFIED: …]` tombstone cites nothing;
    the fidelity pass's composite `[UNVERIFIED, C2]` still cites C2."""
    ids: list[str] = []
    for block in _CITATION_BLOCK_RE.findall(sentence):
        if not block.startswith("[UNVERIFIED:"):
            ids.extend(f"C{n}" for n in _CITATION_ID_RE.findall(block))
    return list(dict.fromkeys(ids))


def _quotations(sentence: str) -> list[str]:
    """Quoted text of three words or more that reads as a quotation of a source —
    not a search phrase ("how to use Notion" search traffic)."""
    found = []
    for match in _QUOTE_RE.finditer(sentence):
        quoted = match.group(1)
        if len(quoted.split()) < 3:
            continue
        around = sentence[max(0, match.start() - 25):match.start()] + " " + sentence[match.end():match.end() + 25]
        if _KEYWORD_CONTEXT_RE.search(around):
            continue
        found.append(quoted)
    return found


#: A scale in a claim's unit: a word ("million USD"), or a letter beside a currency
#: ("USD m", "$M", "M USD") — a bare "m" or "b" is metres or bytes, not a scale.
_UNIT_SCALE_RE = re.compile(r"\b(thousand|million|billion|bn)\b|(?:\b(?:USD|EUR|GBP)\s*|[$€£]\s*)([kmb])\b|\b([kmb])\s*(?:USD|EUR|GBP)\b",
                            re.IGNORECASE)


def _claim_values(claims: list[Any]) -> list[float]:
    """What the cited claims carry: a numeric value (also scaled by its unit —
    value 12, unit "million USD" is 12,000,000), else the numbers in the claim's
    own text (a non-numeric claim can still state a figure)."""
    values: list[float] = []
    for claim in claims:
        value = _numeric(claim)
        if value is not None:
            values.append(value)
            unit = _UNIT_SCALE_RE.search(claim.unit or "")
            if unit:
                word = next(g for g in unit.groups() if g).lower()
                values.append(value * (_SCALE.get(word) or _LETTER_SCALE[word]))
        else:
            values.extend(n for n, _ in _figures(claim.claim) + _numbers(claim.claim))
    return values


def _numeric(claim: Any) -> float | None:
    try:
        return float(str(claim.value).replace(",", "")) if claim.value is not None else None
    except ValueError:
        return None


#: The writer's tag, as it writes it: the upper-case word ("[CONFLICT]", "(CONFLICT)").
_CONFLICT_TAG_RE = re.compile(r"\bCONFLICT\b")
#: A register heading or lead-in: the tag in brackets or parentheses, or the words "conflict register" —
#: not a status legend that merely lists CONFLICT among the statuses.
_CONFLICT_REGISTER_RE = re.compile(r"[\[(]CONFLICT[\])]|(?i:\bconflicts?\s+register\b)")
#: A section named "Source log", numbered or bold as the runbooks write it — not "Source log and findings".
#: A status legend names two or more statuses ("(VERIFIED) checked · (CONFLICT) disagree"): not a register.
_STATUS_WORD_RE = re.compile(r"\b(?:VERIFIED|ASSUMED|CONFLICT|UNVERIFIED)\b")


def _register(text: str) -> bool:
    return _CONFLICT_REGISTER_RE.search(text) is not None and len(set(_STATUS_WORD_RE.findall(text))) < 2


_SOURCE_LOG_HEADING_RE = re.compile(r"^#+\s*(?:\d+[.)]\s*)?(?:\*\*)?source log(?:\*\*)?\s*[:.]?\s*$", re.IGNORECASE)
_DERIVED_RE = re.compile(r"\bderived\b(?!\s+from\b)", re.IGNORECASE)


#: A status tag right after a citation block: "[C17] (VERIFIED)", "[C1, C2] VERIFIED (single source)".
_TAGGED_CITATION_RE = re.compile(r"(\[[^\]]*?\bC\d+[^\]]*?\])\s*\(?\s*VERIFIED\b")


def _status_mislabels(report_md: str, claims: dict[str, Any]) -> list[tuple[str, str]]:
    """(claim id, line) for each citation tagged VERIFIED whose claim the ledger
    does not hold as verified (CORE-09: the writer must not call a claim
    VERIFIED that the ledger marks otherwise)."""
    found = []
    for line in report_md.splitlines():
        for match in _TAGGED_CITATION_RE.finditer(line):
            for ref in (f"C{n}" for n in _CITATION_ID_RE.findall(match.group(1))):
                if ref in claims and claims[ref].status.value != "verified":
                    found.append((ref, line))
    return found


def _conflict_scopes(report_md: str) -> list[tuple[str, bool]]:
    """Each line with whether CONFLICT is disclosed for it: on the line itself,
    in its section heading, or in the lead-in of the list it belongs to (the
    `[CONFLICT] register` the runbooks require). Source-log rows are a register
    of provenance, not findings: a conflict is disclosed where it is reported."""
    out: list[tuple[str, bool]] = []
    heading, lead_in = "", ""
    for line in report_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading, lead_in = stripped, ""
            out.append((line, True))
            continue
        # list items and table rows (separator rows included) belong to the lead-in above them
        bullet = bool(re.match(r"^([-*+]|\d+[.)])\s", stripped)) or stripped.startswith("|")
        if stripped and not bullet:
            lead_in = stripped
        disclosed = (_CONFLICT_TAG_RE.search(stripped) is not None or _register(heading)
                     or (bullet and _register(lead_in))
                     or _SOURCE_LOG_HEADING_RE.match(heading) is not None)
        out.append((line, disclosed))  # a blank line keeps the lead-in: "Register:\n\n- C1 …"
    return out


def _figures(sentence: str) -> list[tuple[float, bool]]:
    """Figures a sentence states, as (value, is_percent), by the writer lint's own
    definition of a metric (`_NUMBER_RE`): a bare number in a name ("Fortune
    500"), a citation, a date or an error band (±n%) is not a figure."""
    text = _CITATION_BLOCK_RE.sub(" ", sentence)
    text = _DATE_RE.sub(" ", text)
    text = re.sub(r"±\s*\d+(?:\.\d+)?\s*%?", " ", text)
    figures = []
    matches = {m.start(): m for m in _NUMBER_RE.finditer(text)}
    for m in _SCALED_RE.finditer(text):
        matches.setdefault(m.start(), m)
    for start in sorted(matches):
        match = matches[start]
        token = match.group(0).rstrip()
        number = float(_LEADING_NUMBER_RE.search(token).group(0).replace(",", ""))
        scale = _SCALE.get(token[-1], 1.0)
        # "$4B", "$30K", "$4.2 million": the scale right after the number
        word = _SCALE_WORD_RE.match(text, match.end()) if scale == 1.0 else None
        if word:
            scale = _SCALE[word.group(1).lower()] if word.group(1) else _LETTER_SCALE[word.group(2).lower()]
        if token.lower().endswith(("thousand", "million", "billion", "bn")):
            scale = _SCALE[re.search(r"(thousand|million|billion|bn)$", token.lower()).group(1)]
        figures.append((number * scale, token.endswith("%")))
    return figures


def _numbers(sentence: str) -> list[tuple[float, bool]]:
    """Bare numbers in a sentence — outside citations, dates and metric figures
    (a number inside "$12M" is 12 million, not 12)."""
    text = _DATE_RE.sub(" ", _CITATION_BLOCK_RE.sub(" ", sentence))
    spans = [m.span() for rx in (_NUMBER_RE, _SCALED_RE) for m in rx.finditer(text)]
    return [(float(m.group(0).replace(",", "")), False) for m in _LEADING_NUMBER_RE.finditer(text)
            if not any(a <= m.start() < b for a, b in spans)]


def _matches(figure: tuple[float, bool], value: float) -> bool:
    number, percent = figure
    candidates = [value, value * 100] if percent else [value]
    return any(abs(number - v) <= max(abs(v) * 0.01, 1e-9) for v in candidates)


_TYPOGRAPHY = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'", "“": '"', "”": '"'})


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_TYPOGRAPHY)).strip().lower()


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s", "e", "ly"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


_WORD_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")


def _backed(quoted: str, claim: Any) -> bool:
    """A quotation is backed by its claim when it is in the claim's quote or text,
    or when at least 70 % of its word stems are (a headline or a phrase restated
    in the claim's words). A sentence may also quote a source's title beside the backed quote:
    the check asks that the citation back at least one quotation."""
    haystack = _norm(" ".join(filter(None, [claim.quote, claim.claim])))
    if _norm(quoted) in haystack:
        return True
    words = [_stem(w) for w in _WORD_RE.findall(_norm(quoted))]
    known = {_stem(w) for w in _WORD_RE.findall(haystack)}
    return bool(words) and sum(w in known for w in words) / len(words) >= 0.7


def code_defects(report_md: str, ledger: Ledger, checkpoint: Checkpoint) -> list[dict[str, str]]:
    """Defects the code proves from the report, the ledger and the checkpoint —
    never a judgement call. Each one vetoes the judge's pass (W6-T1):

    - missing_ref — a citation names no ledger claim;
    - quote_not_in_ledger — a sentence quotes a source (three words or more, not
      a search phrase) and none of its quotations is backed by any claim it
      cites (`_backed`);
    - value_mismatch — a sentence citing only numeric claims states a metric
      figure, and no number in it is any cited claim's value (1 % tolerance);
      a figure marked "derived" (the writer's rule; "derived from" is not the
      mark) is exempt; a non-numeric claim carries the numbers in its text;
    - conflict_hidden — a claim in status conflict is cited on a line that does
      not carry the writer's upper-case CONFLICT tag, under a heading or list
      lead-in that is not a conflict register (`_conflict_scopes`; rows under a
      "Source log" heading excepted);
    - status_mislabel — a citation tagged VERIFIED whose claim the ledger does
      not hold as verified (CORE-09);
    - partial_undisclosed — a partial run that does not say "partial" before its
      first section (`writer.partial_disclosed`, the rule the orchestrator
      enforces on report.md).
    """
    claims = {c.id: c for c in ledger.claims}
    defects: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, claim: str, text: str) -> None:
        if (kind, claim) not in seen:
            seen.add((kind, claim))
            defects.append({"kind": kind, "claim": claim, "text": text.strip()[:200]})

    for ref in lint_report(report_md, ledger).missing_refs:
        add("missing_ref", ref, f"[{ref}] is not in the ledger")
    for ref, line in _status_mislabels(report_md, claims):
        add("status_mislabel", ref, line)
    for line, disclosed in _conflict_scopes(report_md):
        if disclosed:
            continue
        for ref in _cited(line):
            if ref in claims and claims[ref].status.value == "conflict":
                add("conflict_hidden", ref, line)
    for sentence in _sentences(report_md):
        cited = [claims[ref] for ref in _cited(sentence) if ref in claims]
        if not cited or len(cited) != len(_cited(sentence)):
            continue  # an unknown citation is missing_ref's
        quotations = _quotations(sentence)
        if quotations and not any(_backed(q, c) for q in quotations for c in cited):
            add("quote_not_in_ledger", cited[0].id, sentence)
        values = _claim_values(cited)
        figures = _figures(sentence)
        # A metric figure (the writer lint's definition) none of the cited values
        # matches — a bare number may carry the value ("interest 36 [C18]"), and a
        # figure marked "derived" (not "derived from") is the writer's computed one.
        if (figures and values and not _DERIVED_RE.search(sentence)
                and not any(_matches(f, v) for f in figures + _numbers(sentence) for v in values)):
            add("value_mismatch", cited[0].id, sentence)
    if checkpoint.partial and not partial_disclosed(report_md):
        add("partial_undisclosed", "", next((line for line in report_md.splitlines() if line.strip()),
                                            "(empty report head)"))
    return defects


def programmatic_signals(
    report_md: str, ledger: Ledger, checkpoint: Checkpoint, runbook: Runbook
) -> dict[str, Any]:
    lint = lint_report(report_md, ledger)
    budget = runbook.meta.budget
    used = int(checkpoint.counters.get("data_calls", 0))
    issue_count = len(lint.issues)
    sections = section_coverage(report_md, required_sections(runbook))
    ledger_summary = ledger_stats(ledger)
    return {
        "defects": code_defects(report_md, ledger, checkpoint),
        "completeness_cap": (round(len(sections["covered"]) / len(sections["required"]), 3)
                             if sections["required"] else 1.0),
        "source_quality_cap": (ledger_summary["primary_source_ratio"]
                               if ledger_summary["primary_source_ratio"] is not None else 1.0),
        "lint": {
            "missing_refs": lint.missing_refs,
            "uncited_numbers": lint.uncited_numbers,
        },
        "citation_health_cap": round(1.0 / (1 + issue_count), 3),
        "ledger": ledger_summary,
        "sections": sections,
        "budget": {
            "data_calls_used": used,
            "max_tool_calls": budget.max_tool_calls,
            "usage_ratio": (
                round(used / budget.max_tool_calls, 3) if budget.max_tool_calls else None
            ),
            "partial": checkpoint.partial,
            "stop_reason": checkpoint.stop_reason,
        },
    }


_JUDGE_SYSTEM = """\
You are the quality judge for a research report. Score it on five dimensions,
each 0.0-1.0, and output JSON: {"scores": {...}, "reasons": {...}} with exactly
these keys: factual_accuracy, citation_accuracy, completeness, source_quality,
tool_efficiency.

Rubric:
- factual_accuracy: do the report's statements match the ledger claims? Any
  claim contradicted by or absent from the ledger drags this down.
- citation_accuracy: does every number carry a valid [C..] reference? Use the
  programmatic lint output as ground truth — uncited_numbers and missing_refs
  are confirmed defects, and citation_health_cap is the maximum score you may
  give this dimension.
- completeness: does the report cover every required section (see
  programmatic section coverage: covered vs missing)? A partial run must be
  judged against its declared stop_reason, but missing required sections still
  cost score.
- source_quality: are claims backed by primary data tools rather than
  LLM-derived sources? llm_derived_claims lists claim ids from LLM sources;
  primary_source_ratio is the code-computed share from data tools.
- tool_efficiency: data_calls_used vs max_tool_calls, plus whether the run
  stayed focused. Lower usage for full coverage scores higher.

Score honestly against the evidence. The programmatic_signals object is
authoritative — never invent your own counts. Its `defects` are proven by code
(an invented citation or quotation, a figure its claim does not carry, a hidden
conflict, an undisclosed partial run): the report fails on them whatever you
score, so name them in your reasons. completeness_cap and source_quality_cap
bound those two dimensions as citation_health_cap bounds citations."""


def _parse_judge_json(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        try:
            payload = json.loads(match.group(0)) if match else {}
        except json.JSONDecodeError:
            payload = {}
    if not isinstance(payload, dict):
        raise JudgeError("judge returned non-object JSON")
    return payload


class _JudgeLedger:
    """`<run>/judge-ledger.json`: one session per judging, its attempts in the
    run ledger's AttemptRecord shape. Never the run's checkpoint: judging must
    not change what the run recorded."""

    def __init__(self, run_dir: Path, max_usd: float) -> None:
        self.path = run_dir / JUDGE_LEDGER
        try:
            data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}
        except (OSError, json.JSONDecodeError) as exc:
            raise JudgeError(f"{self.path}: unreadable judge ledger ({exc}); move it aside") from exc
        self.sessions: list[dict[str, Any]] = list(data.get("sessions") or [])
        self.attempts: list[AttemptRecord] = []
        from datetime import datetime, timezone

        self.session = {"started_at": datetime.now(timezone.utc).isoformat(), "max_usd": max_usd}
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"judge-{len(self.sessions) + 1}-{self._n}"

    def save(self) -> None:
        session = dict(self.session, attempts=[a.model_dump(mode="json") for a in self.attempts])
        payload = {"schema_version": 1, "sessions": [*self.sessions, session]}
        temp = self.path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.path)


async def judge_run(
    run_dir: Path,
    llm: LLMClient,
    threshold: float = DEFAULT_THRESHOLD,
    *,
    max_usd: float | None = None,
    runbooks_dir: Path | None = None,
) -> JudgeResult:
    report_md, ledger, checkpoint, runbook = load_run(run_dir, runbooks_dir)
    signals = programmatic_signals(report_md, ledger, checkpoint, runbook)
    meter = None
    if max_usd is not None and hasattr(llm, "meter"):
        if not (max_usd > 0):
            raise JudgeError(f"--max-usd must be > 0, got {max_usd!r}")
        book = _JudgeLedger(run_dir, max_usd)
        meter = LlmMeter(max_usd=max_usd, reserve_usd=0.0, attempts=book.attempts, persist=book.save,
                         record_type=AttemptRecord, new_id=book.new_id)
        previous, llm.meter = llm.meter, meter
    try:
        return await _judge(llm, report_md, ledger, signals, threshold, meter)
    except LLMBudgetExceeded as exc:
        raise JudgeError(f"judge budget: {exc}") from exc
    except LLMError as exc:
        # The model did not answer: a judge failure (exit 2), never a FAIL.
        raise JudgeError(f"judge model call failed: {exc}") from exc
    except CheckpointWriteError as exc:
        raise JudgeError(f"judge ledger could not be written: {exc}") from exc
    finally:
        if meter is not None:
            llm.meter = previous


async def _judge(llm, report_md, ledger, signals, threshold, meter) -> JudgeResult:
    user = (
        "## programmatic_signals (authoritative, code-computed)\n"
        + json.dumps(signals, indent=2, ensure_ascii=False)
        + "\n\n## ledger_claims\n"
        + ledger.as_prompt_json()
        + "\n\n## report_markdown\n"
        + report_md[:_REPORT_SNIPPET_CHARS]
    )
    text = await llm.complete(
        [{"role": "system", "content": _JUDGE_SYSTEM}, {"role": "user", "content": user}],
        tier="strong",
        json_mode=True,
        max_tokens=2000,
        temperature=0.0,
        stage="judge",
    )
    payload = _parse_judge_json(text)
    raw_scores = payload.get("scores")
    if not isinstance(raw_scores, dict) or not raw_scores:
        # An unparsable or score-less judge reply is a judge failure, not a
        # 0.00 FAIL — the two must never look alike in eval output.
        raise JudgeError(f"judge returned no usable scores object: {text[:200]!r}")
    raw_reasons = payload.get("reasons") or {}

    scores: dict[str, float] = {}
    for dim in DIMENSIONS:
        try:
            value = float(raw_scores.get(dim, 0.0))
        except (TypeError, ValueError):
            value = 0.0
        scores[dim] = min(1.0, max(0.0, value))
    scores["citation_accuracy"] = min(
        scores["citation_accuracy"], signals["citation_health_cap"]
    )
    scores["completeness"] = min(scores["completeness"], signals["completeness_cap"])
    scores["source_quality"] = min(scores["source_quality"], signals["source_quality_cap"])
    reasons = {dim: str(raw_reasons.get(dim, "")) for dim in DIMENSIONS}
    result = JudgeResult(scores, reasons, signals, threshold)
    result.spend_usd = meter.spend() if meter is not None else None
    return result


def print_result(result: JudgeResult) -> None:
    for dim in DIMENSIONS:
        reason = f" — {result.reasons[dim]}" if result.reasons.get(dim) else ""
        print(f"  {dim:<18} {result.scores[dim]:.2f}  (weight {WEIGHTS[dim]:.2f}){reason}")
    print(f"  {'weighted total':<18} {result.total:.2f}")
    for defect in result.defects:
        print(f"  DEFECT {defect['kind']} {defect['claim']}: {defect['text']}")
    if result.spend_usd is not None:
        print(f"  judge spend        ${result.spend_usd:.4f} (ledger {JUDGE_LEDGER})")
    verdict = "PASS" if result.passed else "FAIL"
    vetoed = " — vetoed by code-proven defects" if result.defects and result.total >= result.threshold else ""
    print(f"{verdict} (threshold {result.threshold}){vetoed}")


async def _amain(args: argparse.Namespace) -> int:
    from research_agent.config import Config, ConfigError

    try:
        config = Config.from_env(require_prowl=False)  # the judge is LLM-only
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    async with LLMClient(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        model_cheap=config.llm_model,
        model_strong=config.llm_model_judge or config.llm_model_strong,
    ) as llm:
        try:
            result = await judge_run(Path(args.run), llm, threshold=args.threshold, max_usd=args.max_usd)
        except JudgeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_ERROR
    print_result(result)
    return EXIT_PASS if result.passed else EXIT_FAIL


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="run directory, e.g. runs/<id>")
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"weighted-total pass threshold (default {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--max-usd", type=float, default=DEFAULT_JUDGE_MAX_USD,
        help=f"the judge's own LLM ceiling for this judging, USD (default {DEFAULT_JUDGE_MAX_USD})",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
