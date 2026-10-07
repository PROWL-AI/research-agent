"""prowl-research CLI."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from research_agent.config import Config, ConfigError
from research_agent.runbook import RunbookError, list_runbooks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="prowl-research",
        description="Runbook-driven research agent over the Prowl MCP tool bank.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-runbooks", help="list available runbooks (offline, no keys needed)")

    run_p = sub.add_parser("run", help="execute a runbook")
    run_p.add_argument("runbook", help="runbook name")
    run_p.add_argument("--run-id", default=None, help="resume or reuse this run id")

    val_p = sub.add_parser("validate", help="validate runbook frontmatter and tool names")
    val_p.add_argument(
        "--online",
        action="store_true",
        help="check tool names against the live Prowl catalog (needs PROWL_API_KEY)",
    )

    sub.add_parser("mcp", help="run as an MCP server (stdio)")

    status_p = sub.add_parser("status", help="show run status from its checkpoint (offline)")
    status_p.add_argument("run_id")

    report_p = sub.add_parser("report", help="print a finished run's report markdown (offline)")
    report_p.add_argument("run_id")

    rewrite_p = sub.add_parser(
        "rewrite",
        help="re-run ONLY the writer for a run (draft + citation repair; LLM key needed, no Prowl spend)",
    )
    rewrite_p.add_argument("run_id")

    args, extra = parser.parse_known_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.command == "list-runbooks":
        return _cmd_list_runbooks()
    if args.command == "run":
        inputs = _parse_input_pairs(extra)
        return asyncio.run(_cmd_run(args.runbook, inputs, args.run_id))
    if args.command == "validate":
        return _cmd_validate(online=args.online)
    if args.command == "mcp":
        from research_agent.mcp_server import serve

        serve()
        return 0
    if args.command == "status":
        return _cmd_status(args.run_id)
    if args.command == "report":
        return _cmd_report(args.run_id)
    if args.command == "rewrite":
        return asyncio.run(_cmd_rewrite(args.run_id))
    return 2


def _cmd_list_runbooks() -> int:
    try:
        runbooks = list_runbooks()
    except RunbookError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not runbooks:
        print("no runbooks found")
        return 0
    name_width = max(len(rb.name) for rb in runbooks)
    for rb in runbooks:
        budget = rb.meta.budget
        budget_s = (
            f"{budget.max_tool_calls} calls / ${budget.max_usd:.2f} / {budget.max_minutes} min"
        )
        description = rb.meta.description.strip().split("\n")[0]
        print(f"{rb.name:<{name_width}}  {budget_s:<28}  {description}")
    return 0


def _parse_input_pairs(extra: list[str]) -> dict[str, object]:
    inputs: dict[str, object] = {}
    index = 0
    while index < len(extra):
        token = extra[index]
        if not token.startswith("--"):
            print(f"error: unexpected argument '{token}' (expected --key value)", file=sys.stderr)
            raise SystemExit(2)
        key = token[2:].replace("-", "_")
        if index + 1 >= len(extra) or extra[index + 1].startswith("--"):
            print(f"error: --{key} needs a value", file=sys.stderr)
            raise SystemExit(2)
        raw = extra[index + 1]
        inputs[key] = [part.strip() for part in raw.split(",") if part.strip()] if "," in raw else raw
        index += 2
    return inputs


async def _cmd_run(runbook_name: str, inputs: dict[str, object], run_id: str | None) -> int:
    from research_agent.agent.orchestrator import InputError, Orchestrator, OrchestratorError
    from research_agent.llm import LLMClient
    from research_agent.prowl_client import ProwlClient

    try:
        config = Config.from_env()
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    async with ProwlClient(
        api_key=config.prowl_api_key, mcp_url=config.prowl_mcp_url
    ) as prowl, LLMClient(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        model_cheap=config.llm_model,
        model_strong=config.llm_model_strong,
    ) as llm:
        orchestrator = Orchestrator(prowl, llm, runs_root=Path("runs"))
        try:
            result = await orchestrator.run(runbook_name, inputs, run_id=run_id)
        except (OrchestratorError, InputError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    print(f"run {result.run_id}: {result.status}")
    print(f"  report: {result.report_path}")
    print(f"  ledger: {result.ledger_path}")
    print(f"  stats:  {result.stats}")
    if result.skipped_steps:
        print(f"  skipped: {len(result.skipped_steps)} steps")
    return 0 if result.status == "complete" else 1


def _cmd_validate(online: bool) -> int:
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    import validate_runbooks

    return validate_runbooks.main(["--online"] if online else ["--offline"])


def _cmd_status(run_id: str) -> int:
    from research_agent.mcp_server import _status_dict

    try:
        status = _status_dict(run_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"run {status['run_id']} ({status['runbook']}): {status['status']}")
    print(f"  steps:    {len(status['completed_steps'])}/{status['planned_steps']} completed, "
          f"{len(status['skipped_steps'])} skipped")
    print(f"  counters: {status['counters']}")
    if status["duration_s"] is not None:
        print(f"  duration: {status['duration_s']}s")
    if status["stop_reason"]:
        print(f"  stop:     {status['stop_reason']}")
    return 0


def _cmd_report(run_id: str) -> int:
    report_path = Path("runs") / run_id / "report.md"
    if not report_path.is_file():
        print(f"error: no report at {report_path}", file=sys.stderr)
        return 1
    print(report_path.read_text(encoding="utf-8"))
    return 0


async def _cmd_rewrite(run_id: str) -> int:
    from research_agent.agent.writer import RewriteError, rewrite_report
    from research_agent.llm import LLMClient
    from research_agent.runbook import RunbookError

    try:
        config = Config.from_env(require_prowl=False)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    async with LLMClient(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        model_cheap=config.llm_model,
        model_strong=config.llm_model_strong,
    ) as llm:
        try:
            outcome = await rewrite_report(llm, Path("runs"), run_id)
        except (RewriteError, RunbookError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    print(
        f"run {run_id}: report rewritten "
        f"(lint {outcome.lint_before} -> {outcome.lint_after} issues"
        f"{'' if outcome.revised else ', no repair needed'})"
    )
    return 0 if outcome.lint_after == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
