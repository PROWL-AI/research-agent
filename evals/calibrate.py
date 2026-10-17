#!/usr/bin/env python3
"""Calibrate the judge against planted-defect fixtures (W6-T1, KA-G02, B-017).

Usage:
  python evals/calibrate.py            # offline: a maximally lenient fake model
  python evals/calibrate.py --live     # the configured judge model (needs a key)

Each fixture in evals/fixtures/planted/*.json is a report, its ledger claims and
a label (pass | fail, with the defect kinds it plants). The harness builds each
into a temporary run, judges it and prints the verdict per fixture, the
agreement with the labels and the judge spend. Offline, the fake model scores
0.95 on every dimension: a planted fixture can only fail through the judge's
code checks, which is what this proves. Live, the agreement number is the
model's own and is recorded as acceptance evidence.

Exit: 0 every verdict matches its label, 1 a planted fixture passed or an honest
one failed, 2 a judge error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import judge  # noqa: E402

from research_agent.evidence.ledger import Ledger  # noqa: E402
from research_agent.evidence.store import Checkpoint  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "planted"
RUNBOOKS = FIXTURES / "runbooks"


class LenientJudge:
    """The most lenient model there is: 0.95 everywhere, no reasons."""

    async def complete(self, messages, tier="cheap", json_mode=False, **kwargs):
        return json.dumps({"scores": {d: 0.95 for d in judge.DIMENSIONS}, "reasons": {}})


def build_run(fixture: dict[str, Any], root: Path) -> Path:
    run_dir = root / fixture["name"]
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "report.md").write_text(fixture["report"], encoding="utf-8")
    ledger = Ledger(run_dir / "ledger.json")
    for claim in fixture["claims"]:
        ledger.add(**claim)
    ledger.save()
    checkpoint = Checkpoint(run_id=fixture["name"], runbook=fixture["runbook"])
    checkpoint.partial = bool(fixture.get("partial"))
    (run_dir / "checkpoint.json").write_text(checkpoint.model_dump_json(), encoding="utf-8")
    return run_dir


async def judge_fixture(fixture: dict[str, Any], llm: Any, root: Path,
                        max_usd: float | None = None) -> dict[str, Any]:
    run_dir = build_run(fixture, root)
    row: dict[str, Any] = {"name": fixture["name"], "label": fixture["label"], "planted": fixture["defects"]}
    try:
        result = await judge.judge_run(run_dir, llm, max_usd=max_usd, runbooks_dir=RUNBOOKS)
    except judge.JudgeError as exc:
        return {**row, "verdict": "ERROR", "error": str(exc), "defects": [], "total": None, "spend_usd": None}
    return {**row, "verdict": "PASS" if result.passed else "FAIL", "total": result.total,
            "defects": result.defects, "spend_usd": result.spend_usd}


async def calibrate(llm: Any, fixtures_dir: Path, root: Path, max_usd: float | None = None) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(fixtures_dir.glob("*.json")):
        rows.append(await judge_fixture(json.loads(path.read_text(encoding="utf-8")), llm, root, max_usd))
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected = {"pass": "PASS", "fail": "FAIL"}
    judged = [r for r in rows if r["verdict"] != "ERROR"]
    agree = sum(r["verdict"] == expected[r["label"]] for r in judged)
    spend = [r["spend_usd"] for r in rows if r.get("spend_usd") is not None]
    return {
        "fixtures": len(rows),
        "agreement": round(agree / len(judged), 3) if judged else None,
        "missed": [r["name"] for r in judged if r["label"] == "fail" and r["verdict"] == "PASS"],
        "false_alarms": [r["name"] for r in judged if r["label"] == "pass" and r["verdict"] == "FAIL"],
        "errors": [r["name"] for r in rows if r["verdict"] == "ERROR"],
        "judge_spend_usd": round(sum(spend), 6) if spend else None,
    }


async def _amain(args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory(prefix="judge-calibration-") as tmp:
        if not args.live:
            rows = await calibrate(LenientJudge(), FIXTURES, Path(tmp))
            model = "lenient fake (0.95 on every dimension)"
        else:
            from research_agent.config import Config, ConfigError
            from research_agent.llm import LLMClient

            try:
                config = Config.from_env(require_prowl=False)  # the judge is LLM-only
            except ConfigError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return judge.EXIT_ERROR
            model = config.llm_model_judge or config.llm_model_strong
            async with LLMClient(base_url=config.llm_base_url, api_key=config.llm_api_key,
                                 model_cheap=config.llm_model, model_strong=model) as llm:
                rows = await calibrate(llm, FIXTURES, Path(tmp), max_usd=args.max_usd)
    summary = summarize(rows)
    for r in rows:
        kinds = ",".join(sorted({d["kind"] for d in r["defects"]})) or "-"
        total = f"{r['total']:.2f}" if r["total"] is not None else "-"
        print(f"  {r['name']:<22} label {r['label']:<4} verdict {r['verdict']:<5} total {total:<5} defects {kinds}")
    print(json.dumps({"model": model, **summary}, ensure_ascii=False))
    if summary["errors"]:
        return judge.EXIT_ERROR
    return judge.EXIT_FAIL if summary["missed"] or summary["false_alarms"] else judge.EXIT_PASS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="judge with the configured model (spends money)")
    parser.add_argument("--max-usd", type=float, default=judge.DEFAULT_JUDGE_MAX_USD,
                        help="the judge's ceiling per fixture, USD (live only)")
    return asyncio.run(_amain(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
