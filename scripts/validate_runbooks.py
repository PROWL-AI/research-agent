#!/usr/bin/env python3
"""Validate every runbook: frontmatter parses, budgets are sane, tool names exist.

Offline mode uses evals/fixtures/live_catalog_snapshot.json.
Online mode queries the live Prowl catalog (needs PROWL_API_KEY only — no LLM
key, the catalog call is not an LLM flow).
Exits 1 on any unknown tool name (trap T1: prose must never name tools that
cannot be called).

Exit codes: 0 = all runbooks valid, 1 = validation failed, 2 = usage or
network/config error (so CI can tell "runbook invalid" apart from "could not
reach the catalog").

TODO: warn when a runbook's allowlist misses the declared failover alternatives
of its tools (trap T2) once a machine-readable alternatives map is available
from the live catalog.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from research_agent.runbook import RunbookError, list_runbooks  # noqa: E402

CATALOG_SNAPSHOT = REPO_ROOT / "evals" / "fixtures" / "live_catalog_snapshot.json"


def check_tools_against_catalog(
    tools: list[str], catalog: list[str]
) -> list[str]:
    live = set(catalog)
    return [name for name in tools if name not in live]


def _budget_problems(budget: object) -> list[str]:
    problems = []
    if budget.max_tool_calls <= 0:
        problems.append("max_tool_calls must be > 0")
    if budget.max_usd <= 0:
        problems.append("max_usd must be > 0")
    if budget.max_minutes <= 0:
        problems.append("max_minutes must be > 0")
    return problems


async def _load_catalog(offline: bool) -> list[str]:
    if offline:
        data = json.loads(CATALOG_SNAPSHOT.read_text(encoding="utf-8"))
        return list(data["tools"])
    from research_agent.config import Config
    from research_agent.prowl_client import ProwlClient

    # Online validation only talks to the Prowl catalog — no LLM key needed.
    config = Config.from_env(require_llm=False)
    async with ProwlClient(api_key=config.prowl_api_key, mcp_url=config.prowl_mcp_url) as client:
        return await client.list_tools()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="use the catalog snapshot fixture")
    mode.add_argument("--online", action="store_true", help="query the live Prowl catalog")
    args = parser.parse_args(argv)
    offline = args.offline or not args.online

    if not offline and not os.environ.get("PROWL_API_KEY"):
        print("error: --online needs PROWL_API_KEY in the environment", file=sys.stderr)
        return 2

    failures = 0

    try:
        runbooks = list_runbooks()
    except RunbookError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    for runbook in runbooks:
        for problem in _budget_problems(runbook.meta.budget):
            print(f"FAIL: {runbook.name}: budget {problem}")
            failures += 1
    print(f"frontmatter: {len(runbooks)} runbook(s) parsed")

    try:
        catalog = asyncio.run(_load_catalog(offline))
    except Exception as exc:
        print(
            f"error: could not load the {'snapshot' if offline else 'live'} catalog: {exc}",
            file=sys.stderr,
        )
        return 2
    print(f"catalog: {len(catalog)} tools ({'snapshot' if offline else 'live'})")

    for runbook in runbooks:
        unknown = check_tools_against_catalog(runbook.meta.tools, catalog)
        if unknown:
            print(f"FAIL: {runbook.name}: unknown tools: {', '.join(unknown)}")
            failures += 1
        else:
            print(f"OK:   {runbook.name}: {len(runbook.meta.tools)} tools all present")

    if failures:
        print(f"\n{failures} validation failure(s)", file=sys.stderr)
        return 1
    print("\nall runbooks valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
