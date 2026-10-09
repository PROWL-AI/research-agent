"""prowl-research CLI."""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research_agent.config import Config, ConfigError
from research_agent.evidence.store import validate_run_id
from research_agent.runbook import RunbookError, list_runbooks

log = logging.getLogger(__name__)


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

    export_p = sub.add_parser("export", help="render a run's report (self-contained HTML or markdown path)")
    export_p.add_argument("run_id")
    export_p.add_argument("--format", choices=["html", "md"], default="html")

    prune_p = sub.add_parser(
        "prune",
        help="delete old runs/<id> directories (dry-run unless --yes is given)",
    )
    prune_p.add_argument(
        "--older-than",
        default="30d",
        metavar="Nd",
        help="minimum age by checkpoint created_at (default: 30d)",
    )
    prune_p.add_argument(
        "--keep-last",
        type=int,
        default=0,
        metavar="N",
        help="never delete the N newest runs, however old",
    )
    prune_p.add_argument(
        "--yes",
        action="store_true",
        help="actually delete; without it prune only lists candidates",
    )

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
    if args.command == "export":
        return _cmd_export(args.run_id, args.format)
    if args.command == "prune":
        return _cmd_prune(args.older_than, args.keep_last, args.yes)
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
    print(
        "\nbudgets cap tool calls only — LLM usage is metered separately "
        "(see stats.llm_usage in run output)"
    )
    return 0


def _parse_input_pairs(extra: list[str]) -> dict[str, object]:
    inputs: dict[str, object] = {}
    index = 0
    while index < len(extra):
        token = extra[index]
        if not token.startswith("--"):
            print(f"error: unexpected argument '{token}' (expected --key value)", file=sys.stderr)
            raise SystemExit(2)
        raw_key = token[2:]
        if "=" in raw_key:
            name, _, value = raw_key.partition("=")
            inputs[name.replace("-", "_")] = value
            index += 1
            continue
        key = raw_key.replace("-", "_")
        if index + 1 >= len(extra) or extra[index + 1].startswith("--"):
            print(f"error: --{key} needs a value", file=sys.stderr)
            raise SystemExit(2)
        # Keep the raw string: comma-splitting happens in build_brief, which
        # knows the runbook input type — a string input may contain commas.
        inputs[key] = extra[index + 1]
        index += 2
    return inputs


def _mark_run_failed(runbook_name: str, run_id: str, exc: Exception) -> None:
    """Mirror the MCP contract: a crashed run's checkpoint becomes 'failed'
    with a stop_reason — the CLI has no MCP wrapper doing this for it."""
    from research_agent.evidence.store import ArtifactStore

    try:
        store = ArtifactStore(Path("runs") / run_id)
        checkpoint = store.load_checkpoint()
        # Only a checkpoint this run owns: a precondition failure must not
        # rewrite another run's terminal state.
        if (
            checkpoint is not None
            and checkpoint.status == "running"
            and checkpoint.runbook == runbook_name
        ):
            checkpoint.status = "failed"
            checkpoint.stop_reason = str(exc)[:300]
            store.save_checkpoint(checkpoint)
    except Exception as mark_exc:  # noqa: BLE001
        log.warning("could not mark run %s as failed: %s", run_id, mark_exc)


async def _cmd_run(runbook_name: str, inputs: dict[str, object], run_id: str | None) -> int:
    if run_id is not None:
        try:
            validate_run_id(run_id)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    from research_agent.agent.orchestrator import InputError, Orchestrator, OrchestratorError
    from research_agent.llm import LLMClient
    from research_agent.prowl_client import ProwlClient

    try:
        config = Config.from_env()
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Generate the id up front (same shape as the orchestrator's) so a crash
    # below can mark this run's checkpoint failed instead of leaving it
    # 'running' forever.
    run_id = run_id or Orchestrator._new_run_id(runbook_name)

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
        except RunbookError as exc:
            # Usage error (unknown/invalid runbook) — README promises exit 2.
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except (OrchestratorError, InputError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            _mark_run_failed(runbook_name, run_id, exc)
            return 1
        except Exception as exc:
            print(f"error: run failed: {exc}", file=sys.stderr)
            _mark_run_failed(runbook_name, run_id, exc)
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
    try:
        validate_run_id(run_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    from research_agent.mcp_server import _status_dict

    try:
        status = _status_dict(run_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"run {status['run_id']} ({status['runbook']}): {status['status']}")
    # Skipped steps are also recorded in completed_steps (their post-failure
    # chunk-mates) — subtract them or the count overstates real progress.
    skipped_idx = {entry.get("index") for entry in status["skipped_steps"]}
    completed = sum(1 for i in status["completed_steps"] if i not in skipped_idx)
    print(f"  steps:    {completed}/{status['planned_steps']} completed, "
          f"{len(status['skipped_steps'])} skipped")
    print(f"  counters: {status['counters']}")
    if status["duration_s"] is not None:
        print(f"  duration: {status['duration_s']}s")
    if status["stop_reason"]:
        print(f"  stop:     {status['stop_reason']}")
    return 0


def _cmd_report(run_id: str) -> int:
    try:
        validate_run_id(run_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    report_path = Path("runs") / run_id / "report.md"
    if not report_path.is_file():
        print(f"error: no report at {report_path}", file=sys.stderr)
        return 1
    print(report_path.read_text(encoding="utf-8"))
    return 0


async def _cmd_rewrite(run_id: str) -> int:
    try:
        validate_run_id(run_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
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


def _cmd_export(run_id: str, fmt: str) -> int:
    try:
        validate_run_id(run_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    run_dir = Path("runs") / run_id
    if fmt == "md":
        report_path = run_dir / "report.md"
        if not report_path.is_file():
            print(f"error: no report at {report_path}", file=sys.stderr)
            return 1
        print(report_path)
        return 0
    from research_agent.report.render import RenderError, render_run

    try:
        out_path = render_run(run_dir)
    except RenderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(out_path)
    return 0


def _parse_days(text: str) -> timedelta:
    match = re.fullmatch(r"(\d+)d", text.strip())
    if not match:
        raise ValueError(f"--older-than expects '<N>d' (e.g. 30d), got '{text}'")
    return timedelta(days=int(match.group(1)))


def _lock_held(lock_path: Path) -> bool:
    """True when another process holds an flock on the run's .lock file."""
    import fcntl

    try:
        fd = lock_path.open("r+b")
    except OSError:
        return False
    with fd:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
    return False


def _cmd_prune(older_than: str, keep_last: int, yes: bool) -> int:
    try:
        min_age = _parse_days(older_than)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if keep_last < 0:
        print("error: --keep-last must be >= 0", file=sys.stderr)
        return 2
    from research_agent.evidence.store import ArtifactStore

    runs_root = Path("runs")
    if not runs_root.is_dir():
        print("no runs/ directory — nothing to prune")
        return 0

    now = datetime.now(timezone.utc)
    dated: list[tuple[Path, datetime, str]] = []
    skipped: list[tuple[Path, str]] = []
    for run_dir in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        try:
            checkpoint = ArtifactStore(run_dir).load_checkpoint()
        except Exception:
            checkpoint = None
        if checkpoint is None:
            skipped.append((run_dir, "no readable checkpoint, age unknown"))
            continue
        created = datetime.fromisoformat(checkpoint.created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        dated.append((run_dir, created, checkpoint.status))

    protected = {path for path, _, _ in sorted(dated, key=lambda row: row[1], reverse=True)[:keep_last]}
    candidates: list[tuple[Path, timedelta, str]] = []
    for run_dir, created, status in dated:
        age = now - created
        if run_dir in protected:
            skipped.append((run_dir, "protected by --keep-last"))
        elif age < min_age:
            skipped.append((run_dir, f"only {age.days}d old"))
        elif (run_dir / ".lock").exists() and _lock_held(run_dir / ".lock"):
            # A live lock means a running/interrupted run is still active in
            # another process — deleting its artifacts mid-write is corruption.
            skipped.append((run_dir, f"lock held (status={status})"))
        else:
            candidates.append((run_dir, age, status))

    for run_dir, reason in skipped:
        print(f"skip    {run_dir.name}: {reason}")
    for run_dir, age, status in candidates:
        print(f"{'delete' if yes else 'would delete'}  {run_dir.name}: {age.days}d old, status={status}")
        if yes:
            shutil.rmtree(run_dir)
    if not yes and candidates:
        print(f"\ndry-run: {len(candidates)} run(s) would be deleted — re-run with --yes to delete")
    else:
        print(f"\n{len(candidates)} run(s) {'deleted' if yes else 'to prune'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
