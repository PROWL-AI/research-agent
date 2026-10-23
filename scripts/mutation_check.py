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
#: the code checks the judge vetoes on (moved from J by B-057)
RC = "research_agent/agent/report_checks.py"
JT = ["tests/test_judge_calibration.py", "tests/test_judge.py"]
MUTANTS = [
    ("chart-not-quote", RC, "    if _FENCED_RE.match(sentence):\n        return []\n", "", JT),
    ("quote-gap", RC, "        if quoted != quoted.strip() or \" | \" in quoted:\n", "        if False:\n", JT),
    # B-060: honest shapes a real report used: assumption marker, template label, conflict-tag ids
    ("assumption-marker", RC, "and not _ASSUMPTION_RE.search(sentence)", "", JT),
    ("label-figure", RC, "figures = _figures(_LABEL_FIGURE_RE.sub(\" \", sentence))", "figures = _figures(sentence)", JT),
    ("conflict-tag-ids", RC, "_cited(_CONFLICT_REF_RE.sub(\" \", sentence))", "_cited(sentence)", JT),
    # W6-T1 — judge vetoes and metering
    ("veto", J, "self.passed = self.total >= threshold and not self.defects", "self.passed = self.total >= threshold", JT),
    ("missing_ref", RC, 'add("missing_ref", ref,', 'None and add("missing_ref", ref,', JT),
    ("quote", RC, 'add("quote_not_in_ledger", cited[0].id, sentence)', "pass", JT),
    ("value", RC, 'add("value_mismatch", value_cited[0].id, sentence)', "pass", JT),
    ("conflict", RC, 'add("conflict_hidden", ref, line)', "pass", JT),
    ("partial", RC, "if checkpoint is not None and checkpoint.partial and not partial_disclosed(report_md):", "if False:", JT),
    ("quote-backing", RC, "/ len(words) >= 0.7", "/ len(words) >= 0.0", JT),
    ("figure-name", RC, "matches = {m.start(): m for m in _NUMBER_RE.finditer(text)}",
     'matches = {m.start(): m for m in re.finditer(r"\\d[\\d,]*(?:\\.\\d+)?", text)}', JT),
    ("scale-suffix", RC, "word = _SCALE_WORD_RE.match(text, match.end()) if scale == 1.0 else None", "word = None", JT),
    ("meter", J, "previous, llm.meter = llm.meter, meter", "previous = llm.meter", JT),
    ("completeness-cap", J, 'scores["completeness"] = min(scores["completeness"], signals["completeness_cap"])', "pass", JT),
    # W6 fix round
    ("llm-error-exit-2", J, "    except LLMError as exc:\n", "    except ZeroDivisionError as exc:\n", JT),
    ("judge-no-prowl", J, "Config.from_env(require_prowl=False)", "Config.from_env()", JT),
    ("register-heading", RC, " or _register(heading)\n", "\n", JT),
    ("register-lead-in", RC, "or (bullet and _register(lead_in))", "", JT),
    ("legend-not-register", RC, "and len(set(_STATUS_WORD_RE.findall(text))) < 2", "", JT),
    ("source-log-rows", RC, "or _SOURCE_LOG_HEADING_RE.match(heading) is not None)", ")", JT),
    ("conflict-tag-exact", RC, 'disclosed = (_CONFLICT_TAG_RE.search(stripped) is not None', 'disclosed = ("conflict" in stripped.lower()', JT),
    ("table-register", RC, 'or stripped.startswith("|")', "", JT),
    ("abbreviation", RC, "if parts and _ABBREVIATION_RE.search(parts[-1]):", "if False:", JT),
    ("composite-unverified", RC, 'if not block.startswith("[UNVERIFIED:"):', 'if not block.startswith("[UNVERIFIED"):', JT),
    ("keyword-quote", RC, "        if _KEYWORD_CONTEXT_RE.search(around):\n            continue\n", "", JT),
    ("multi-cite", RC, "if not cited or len(cited) != len(_cited(sentence)):", "if len(cited) != 1 or len(_cited(sentence)) != 1:", JT),
    ("bare-numbers", RC, "for f in figures + _numbers(sentence)", "for f in figures", JT),
    ("derived", RC, "and not _DERIVED_RE.search(sentence)", "", JT),
    ("derived-from", RC, '_DERIVED_RE = re.compile(r"\\bderived\\b(?!\\s+from\\b)", re.IGNORECASE)', '_DERIVED_RE = re.compile(r"derived", re.IGNORECASE)', JT),
    ("scaled-number-span", RC, "if not any(a <= m.start() < b for a, b in spans)", "if True", JT),
    ("non-numeric-claim-text", RC, "values.extend(n for n, _ in _figures(claim.claim) + _numbers(claim.claim))", "pass", JT),
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
    ("source-log-numbered", RC, "(?:\\d+[.)]\\s*)?(?:\\*\\*)?source log", "source log", JT),
    ("source-log-exact", RC, "source log(?:\\*\\*)?\\s*[:.]?\\s*$", "source log", JT),
    ("unit-scale", RC, "values.append(value * (_SCALE.get(word) or _LETTER_SCALE[word]))", "pass", JT),
    # (register-bracketed retired: since the legend rule, a bare CONFLICT in a heading is covered by legend-not-register)
    ("partially", "research_agent/agent/writer.py", r"\bpartial(?:ly)?\b", r"\bpartial\b", JT),
    ("dry-run-exit-2", "scripts/install-fabric-service.py", "if problem:\n            raise SystemExit(2)", "if False:\n            raise SystemExit(2)", JT),
    # B-045
    ("status-mislabel", RC, 'add("status_mislabel", ref, line)', "pass", JT),
    # B-046 / B-047
    ("impartial-word", "research_agent/agent/writer.py", r'return re.search(r"\bpartial(?:ly)?\b", report_head(report_md), re.IGNORECASE) is not None',
     'return "partial" in report_head(report_md).lower()', JT),
    ("register-parenthesised", RC, r'_CONFLICT_REGISTER_RE = re.compile(r"[\[(]CONFLICT[\])]|', r'_CONFLICT_REGISTER_RE = re.compile(r"\[CONFLICT\]|', JT),
    ("unit-letter-needs-currency", RC, r'|(?:\b(?:USD|EUR|GBP)\s*|[$€£]\s*)([kmb])\b|\b([kmb])\s*(?:USD|EUR|GBP)\b"', r'|\b([kmb])\b|\b(x)\b"', JT),
    ("chain-note", "research_agent/service/static/app.js", "+(j.chainOwner?` <span", "+(false?` <span", ["tests/test_dashboard_labels.py"]),
    ("dry-run-problem", "scripts/install-fabric-service.py", 'problem = None if held else f"vault', 'problem = None if True else f"vault',
     ["tests/test_installer.py"]),
    ("installer-held-slots", "scripts/install-fabric-service.py", "held = [s for s in SLOTS if s not in missing]", "held = list(SLOTS)",
     ["tests/test_installer.py"]),
    # B-070 / B-071: a step whose argument is template text or a known-refused value is not sent
    ("template-not-sent", "research_agent/agent/subagent.py", "    template = template_text(arguments)\n", "    template = []\n",
     ["tests/test_not_sent_arguments.py"]),
    ("limit-not-sent", "research_agent/agent/subagent.py", "    limits = tool_limits.refused(tool, arguments)\n", "    limits = []\n",
     ["tests/test_not_sent_arguments.py"]),
    ("direct-limit-refused", "research_agent/service/runtime.py", "        refuse_known_limits(request)\n", "",
     ["tests/test_not_sent_arguments.py"]),
    ("coverage-told", "research_agent/agent/writer.py", "    if coverage_notes:\n        # B-071", "    if False:\n        # B-071",
     ["tests/test_not_sent_arguments.py"]),
    ("not-sent-complete-run", "research_agent/agent/writer.py", "        if not_sent:\n            partial_note = (",
     "        if False:\n            partial_note = (", ["tests/test_not_sent_arguments.py"]),
    ("live-recheck", "research_agent/service/runtime.py", "            refuse_known_limits(req)\n        async with", "        async with",
     ["tests/test_not_sent_arguments.py"]),
    ("live-spelling", "research_agent/service/runtime.py", 'params = tool_limits.canonical(req["tool"], req["params"])',
     'params = req["params"]', ["tests/test_not_sent_arguments.py"]),
    ("dispatch-refusal-reason", "research_agent/service/runtime.py", "        except LimitRefused as exc:\n", "        except ZeroDivisionError as exc:\n",
     ["tests/test_not_sent_arguments.py"]),
    ("resend-same-params", "research_agent/agent/subagent.py", "        if resend:\n            # A re-send",
     "        if False:\n            # A re-send", ["tests/test_not_sent_arguments.py"]),
    ("resend-not-judged", "research_agent/agent/subagent.py", "reason = None if resend else _not_sent_reason(",
     "reason = _not_sent_reason(", ["tests/test_not_sent_arguments.py"]),
    ("providers-spelling", "research_agent/agent/subagent.py", "        arguments = tool_limits.canonical(record.tool, arguments)\n", "",
     ["tests/test_not_sent_arguments.py"]),
    ("terminal-code-in-data", "research_agent/service/runtime.py",
     'error = {**error, "data": {**error.get("data", {}), "terminalCode": checkpoint.terminal_code}}',
     'error = {**error, "terminalCode": checkpoint.terminal_code}', ["tests/test_ka_contracts.py"]),
    ("legacy-error-served-in-data", "research_agent/service/protocol.py",
     'view["error"] = interop_error(job["error"])', 'view["error"] = job["error"]', ["tests/test_service.py"]),
    ("dashboard-coverage-derived", "research_agent/service/app.py",
     'return {"coverage": tool_limits.statements_ru(tools)}', 'return {"coverage": []}', ["tests/test_service.py"]),
    ("output-judged-as-planned", "research_agent/agent/subagent.py",
     "reason = None if resend else _not_sent_reason(record.tool, judged, missing, ambiguous)",
     "reason = None if resend else _not_sent_reason(record.tool, arguments, missing, ambiguous)", ["tests/test_plan_outputs.py"]),
    ("output-filled-from-raw", "research_agent/agent/subagent.py",
     'found["output:" + name] = output_text(text)', 'found["output:" + name] = name', ["tests/test_plan_outputs.py"]),
    ("output-waits-for-its-step", "research_agent/agent/subagent.py",
     "depth = 1 + max((level[n] for n in output_refs(record.arguments) if n in level), default=-1)", "depth = 0",
     ["tests/test_plan_outputs.py"]),
    ("output-strips-billing", "research_agent/agent/subagent.py",
     "text = json.dumps(_strip_envelope_meta(json.loads(text)), ensure_ascii=False, separators=(\",\", \":\"))",
     "text = text", ["tests/test_plan_outputs.py"]),
    ("legacy-key-is-a-resend", "research_agent/agent/subagent.py",
     "(bool(record.legacy_key) and not any(a.step_id == record.step_id for a in checkpoint.attempts))", "False",
     ["tests/test_m1_tail.py"]),
    ("usage-30-utc-days", "research_agent/service/store.py", "timedelta(days=29)).date()", "timedelta(days=30)).date()",
     ["tests/test_service.py"]),
    ("output-cap-per-step", "research_agent/agent/subagent.py", "share = OUTPUT_CAP // max(1, len(refs))",
     "share = OUTPUT_CAP", ["tests/test_m1_tail.py"]),
    ("forwarding-step-keeps-its-call", "research_agent/agent/orchestrator.py", "            ctx.reserved_calls = later\n",
     "            ctx.reserved_calls = 0\n", ["tests/test_m1_tail.py"]),
    ("service-events-in-file-log", "research_agent/service/store.py",
     "        emit(log, kind, _LOG_LEVELS.get(level, logging.INFO), **fields)\n", "", ["tests/test_service_parity.py"]),
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
