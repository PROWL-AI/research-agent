#!/usr/bin/env python3
"""Plant each listed defect in the code, run its tests, and require them to fail.

Usage: python scripts/mutation_check.py [--only NAME]

Every row is (name, file, original text, mutated text, tests). The original
text must occur exactly once; the file is restored whatever happens. A mutant
that leaves its tests green is SURVIVED and the exit code is 1: the defence it
removed is not load-bearing for any test. The list holds the defences of the
latest certified changes; a receipt is the printed table
(docs/evidence/judge-calibration/mutations.log).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
J = "evals/judge.py"
JT = ["tests/test_judge_calibration.py", "tests/test_judge.py"]
MUTANTS = [
    # W6-T1 — judge vetoes and metering
    ("veto", J, "self.passed = self.total >= threshold and not self.defects", "self.passed = self.total >= threshold", JT),
    ("missing_ref", J, 'add("missing_ref", ref,', 'None and add("missing_ref", ref,', JT),
    ("quote", J, 'add("quote_not_in_ledger", cited[0].id, sentence)', "pass", JT),
    ("value", J, 'add("value_mismatch", cited[0].id, sentence)', "pass", JT),
    ("conflict", J, 'add("conflict_hidden", ref, line)', "pass", JT),
    ("partial", J, "if checkpoint.partial and not partial_disclosed(report_md):", "if False:", JT),
    ("quote-backing", J, "/ len(words) >= 0.7", "/ len(words) >= 0.0", JT),
    ("figure-name", J, "matches = {m.start(): m for m in _NUMBER_RE.finditer(text)}",
     'matches = {m.start(): m for m in re.finditer(r"\\d[\\d,]*(?:\\.\\d+)?", text)}', JT),
    ("scale-suffix", J, "word = _SCALE_WORD_RE.match(text, match.end()) if scale == 1.0 else None", "word = None", JT),
    ("meter", J, "previous, llm.meter = llm.meter, meter", "previous = llm.meter", JT),
    ("completeness-cap", J, 'scores["completeness"] = min(scores["completeness"], signals["completeness_cap"])', "pass", JT),
    # W6 fix round
    ("llm-error-exit-2", J, "    except LLMError as exc:\n", "    except ZeroDivisionError as exc:\n", JT),
    ("judge-no-prowl", J, "Config.from_env(require_prowl=False)", "Config.from_env()", JT),
    ("register-heading", J, 'or "CONFLICT" in heading.upper()', "", JT),
    ("register-lead-in", J, 'or (bullet and "CONFLICT" in lead_in.upper())', "", JT),
    ("source-log-rows", J, 'or "source log" in heading.lower())', ")", JT),
    ("abbreviation", J, "if parts and _ABBREVIATION_RE.search(parts[-1]):", "if False:", JT),
    ("composite-unverified", J, 'if not block.startswith("[UNVERIFIED:"):', 'if not block.startswith("[UNVERIFIED"):', JT),
    ("keyword-quote", J, "        if _KEYWORD_CONTEXT_RE.search(around):\n            continue\n", "", JT),
    ("multi-cite", J, "if not cited or len(cited) != len(_cited(sentence)):", "if len(cited) != 1 or len(_cited(sentence)) != 1:", JT),
    ("bare-numbers", J, "for f in figures + _numbers(sentence)", "for f in figures", JT),
    ("derived", J, 'and "derived" not in sentence.lower()', "", JT),
    ("orchestrator-discloses", "research_agent/agent/orchestrator.py",
     "        if checkpoint.partial:\n            # The writer was told only", "        if False:\n            # The writer was told only",
     ["tests/test_llm_budget.py"]),
    ("resume-replay", "research_agent/service/runtime.py", "        if existing is not None:\n            return existing\n", "",
     ["tests/test_service_parity.py"]),
    ("resume-keeps-delegation", "research_agent/service/runtime.py",
     'delegation = self.store.job(request["resumeJobId"]).get("delegation")', "pass", ["tests/test_service_parity.py"]),
    ("installer-held-slots", "scripts/install-fabric-service.py", "held=[s for s in SLOTS if s not in missing]", "held=list(SLOTS)",
     ["tests/test_installer.py"]),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only")
    args = parser.parse_args()
    survived = 0
    for name, rel, old, new, tests in MUTANTS:
        if args.only and name != args.only:
            continue
        path = ROOT / rel
        source = path.read_text(encoding="utf-8")
        if source.count(old) != 1:
            print(f"{name:24} STALE    the original text occurs {source.count(old)} times in {rel}")
            survived += 1
            continue
        path.write_text(source.replace(old, new), encoding="utf-8")
        try:
            run = subprocess.run([sys.executable, "-m", "pytest", *tests, "-q", "-x", "-p", "no:cacheprovider"],
                                 cwd=ROOT, capture_output=True, text=True)
        finally:
            path.write_text(source, encoding="utf-8")
        killed = run.returncode != 0
        survived += not killed
        last = run.stdout.strip().splitlines()[-1] if run.stdout.strip() else ""
        print(f"{name:24} {'KILLED  ' if killed else 'SURVIVED'} {rel}  ({last})")
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main())
