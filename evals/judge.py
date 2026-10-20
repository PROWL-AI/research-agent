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

from research_agent.agent.writer import lint_report  # noqa: E402
from research_agent.evidence.ledger import Ledger  # noqa: E402
from research_agent.evidence.source import is_llm_answer, is_transform  # noqa: E402
from research_agent.evidence.store import ArtifactStore, Checkpoint  # noqa: E402
from research_agent.evidence.store import AttemptRecord, CheckpointWriteError  # noqa: E402
from research_agent.llm import LLMBudgetExceeded, LLMClient, LLMError, LlmMeter  # noqa: E402
from research_agent.agent.orchestrator import _complete_escalating  # noqa: E402
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


from research_agent.agent.report_checks import code_defects  # noqa: E402,F401


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
    # A cut answer is asked once more with a larger budget, never looped (B-056:
    # the judge's own call was cut at 2000 tokens on a real 44-step report).
    text = await _complete_escalating(
        llm,
        [{"role": "system", "content": _JUDGE_SYSTEM}, {"role": "user", "content": user}],
        2000, 6000,
        tier="strong",
        json_mode=True,
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
