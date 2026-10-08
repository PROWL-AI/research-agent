#!/usr/bin/env python3
"""LLM judge for a finished run: 5-dimension quality rubric.

Usage: python evals/judge.py --run runs/<id> [--threshold 0.7]

Programmatic signals (lint output, ledger stats, section coverage, budget
counters) are computed in code and injected into the judge prompt — the LLM
never sees a number the code did not produce. The citation dimension is
capped by the programmatic lint result so an uncited report cannot be talked
into a pass.
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
from research_agent.evidence.store import Checkpoint  # noqa: E402
from research_agent.llm import LLMClient  # noqa: E402
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

LLM_DERIVED_PREFIXES = (
    "perplexity_",
    "gemini_",
    "google_ai_mode",
    "dataforseo_ai_",
)

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
        self.passed = self.total >= threshold


def load_run(run_dir: Path) -> tuple[str, Ledger, Checkpoint, Runbook]:
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
    checkpoint = Checkpoint.model_validate_json(checkpoint_path.read_text(encoding="utf-8"))
    runbook = get_runbook(checkpoint.runbook)
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
        c.id for c in claims if c.source_tool.startswith(LLM_DERIVED_PREFIXES)
    ]
    by_status: dict[str, int] = {}
    for claim in claims:
        by_status[claim.status.value] = by_status.get(claim.status.value, 0) + 1
    return {
        "claims": len(claims),
        "by_status": by_status,
        "llm_derived_claims": llm_derived,
        "primary_source_ratio": (
            round((len(claims) - len(llm_derived)) / len(claims), 3) if claims else None
        ),
    }


def programmatic_signals(
    report_md: str, ledger: Ledger, checkpoint: Checkpoint, runbook: Runbook
) -> dict[str, Any]:
    lint = lint_report(report_md, ledger)
    budget = runbook.meta.budget
    used = int(checkpoint.counters.get("data_calls", 0))
    issue_count = len(lint.issues)
    return {
        "lint": {
            "missing_refs": lint.missing_refs,
            "uncited_numbers": lint.uncited_numbers,
        },
        "citation_health_cap": round(1.0 / (1 + issue_count), 3),
        "ledger": ledger_stats(ledger),
        "sections": section_coverage(report_md, required_sections(runbook)),
        "budget": {
            "data_calls_used": used,
            "max_tool_calls": budget.max_tool_calls,
            "usage_ratio": round(used / budget.max_tool_calls, 3),
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
authoritative — never invent your own counts."""


def _parse_judge_json(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        payload = json.loads(match.group(0)) if match else {}
    if not isinstance(payload, dict):
        raise JudgeError("judge returned non-object JSON")
    return payload


async def judge_run(
    run_dir: Path,
    llm: LLMClient,
    threshold: float = DEFAULT_THRESHOLD,
) -> JudgeResult:
    report_md, ledger, checkpoint, runbook = load_run(run_dir)
    signals = programmatic_signals(report_md, ledger, checkpoint, runbook)

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
    )
    payload = _parse_judge_json(text)
    raw_scores = payload.get("scores") or {}
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
    reasons = {dim: str(raw_reasons.get(dim, "")) for dim in DIMENSIONS}
    return JudgeResult(scores, reasons, signals, threshold)


def print_result(result: JudgeResult) -> None:
    for dim in DIMENSIONS:
        reason = f" — {result.reasons[dim]}" if result.reasons.get(dim) else ""
        print(f"  {dim:<18} {result.scores[dim]:.2f}  (weight {WEIGHTS[dim]:.2f}){reason}")
    print(f"  {'weighted total':<18} {result.total:.2f}")
    verdict = "PASS" if result.passed else "FAIL"
    print(f"{verdict} (threshold {result.threshold})")


async def _amain(args: argparse.Namespace) -> int:
    from research_agent.config import Config, ConfigError

    try:
        config = Config.from_env()
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    async with LLMClient(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        model_cheap=config.llm_model,
        model_strong=config.llm_model_strong,
    ) as llm:
        try:
            result = await judge_run(Path(args.run), llm, threshold=args.threshold)
        except JudgeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    print_result(result)
    return 0 if result.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="run directory, e.g. runs/<id>")
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"weighted-total pass threshold (default {DEFAULT_THRESHOLD})",
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
