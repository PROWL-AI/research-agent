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
    ("register-heading", J, "or _CONFLICT_REGISTER_RE.search(heading) is not None", "", JT),
    ("register-lead-in", J, "or (bullet and _CONFLICT_REGISTER_RE.search(lead_in) is not None)", "", JT),
    ("source-log-rows", J, "or _SOURCE_LOG_HEADING_RE.match(heading) is not None)", ")", JT),
    ("conflict-tag-exact", J, 'disclosed = (_CONFLICT_TAG_RE.search(stripped) is not None', 'disclosed = ("conflict" in stripped.lower()', JT),
    ("table-register", J, 'or stripped.startswith("|")', "", JT),
    ("abbreviation", J, "if parts and _ABBREVIATION_RE.search(parts[-1]):", "if False:", JT),
    ("composite-unverified", J, 'if not block.startswith("[UNVERIFIED:"):', 'if not block.startswith("[UNVERIFIED"):', JT),
    ("keyword-quote", J, "        if _KEYWORD_CONTEXT_RE.search(around):\n            continue\n", "", JT),
    ("multi-cite", J, "if not cited or len(cited) != len(_cited(sentence)):", "if len(cited) != 1 or len(_cited(sentence)) != 1:", JT),
    ("bare-numbers", J, "for f in figures + _numbers(sentence)", "for f in figures", JT),
    ("derived", J, "and not _DERIVED_RE.search(sentence)", "", JT),
    ("derived-from", J, '_DERIVED_RE = re.compile(r"\\bderived\\b(?!\\s+from\\b)", re.IGNORECASE)', '_DERIVED_RE = re.compile(r"derived", re.IGNORECASE)', JT),
    ("scaled-number-span", J, "if not any(a <= m.start() < b for a, b in spans)", "if True", JT),
    ("non-numeric-claim-text", J, "values.extend(n for n, _ in _figures(claim.claim) + _numbers(claim.claim))", "pass", JT),
    ("judge-ledger-error", J, "    except CheckpointWriteError as exc:\n", "    except ZeroDivisionError as exc:\n", JT),
    ("rewrite-discloses", "research_agent/agent/writer.py",
     "report_md = disclose_partial(outcome.report_md, checkpoint.stop_reason) if checkpoint.partial else outcome.report_md",
     "report_md = outcome.report_md", ["tests/test_llm_budget.py"]),
    ("orchestrator-discloses", "research_agent/agent/orchestrator.py",
     "        if checkpoint.partial:\n            # The writer was told only", "        if False:\n            # The writer was told only",
     ["tests/test_llm_budget.py"]),
    ("resume-replay", "research_agent/service/runtime.py", "        if existing is not None:\n            return existing\n", "",
     ["tests/test_service_parity.py"]),
    ("chain-owner", "research_agent/service/runtime.py",
     'chain_owner = previous.get("chainOwner") or previous.get("delegation")', "chain_owner = None", ["tests/test_service_parity.py"]),
    ("owned-by-chain", "research_agent/service/delegation.py",
     'for who in (job.get("delegation"), job.get("chainOwner")) if who)', 'for who in (job.get("delegation"),) if who)',
     ["tests/test_service_parity.py"]),
    # third round
    ("source-log-numbered", J, "(?:\\d+[.)]\\s*)?(?:\\*\\*)?source log", "source log", JT),
    ("source-log-exact", J, "source log(?:\\*\\*)?\\s*[:.]?\\s*$", "source log", JT),
    ("unit-scale", J, "values.append(value * (_SCALE.get(word) or _LETTER_SCALE[word]))", "pass", JT),
    ("register-bracketed", J, '_CONFLICT_REGISTER_RE = re.compile(r"\\[CONFLICT\\]|', '_CONFLICT_REGISTER_RE = re.compile(r"\\bCONFLICT\\b|', JT),
    ("partially", "research_agent/agent/writer.py", r"\bpartial(?:ly)?\b", r"\bpartial\b", JT),
    ("dry-run-exit-2", "scripts/install-fabric-service.py", "if problem:raise SystemExit(2)", "if False:raise SystemExit(2)", JT),
    ("dry-run-problem", "scripts/install-fabric-service.py", 'problem=None if held else f"vault', 'problem=None if True else f"vault',
     ["tests/test_installer.py"]),
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
