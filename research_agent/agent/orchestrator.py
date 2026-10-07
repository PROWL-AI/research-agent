"""Phase-1 orchestrator: brief → plan → execute → write, with checkpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from research_agent.agent.writer import produce_report
from research_agent.evidence.ledger import Ledger
from research_agent.evidence.store import ArtifactStore, Checkpoint
from research_agent.llm import LLMClient
from research_agent.prowl_client import ProwlClient, ProwlError
from research_agent.runbook import Runbook, RunbookInput, get_runbook

log = logging.getLogger(__name__)

_RAW_SNIPPET_CHARS = 12_000
_TRANSFORM_CONTEXT_CHARS = 4_000
_TRANSFORM_CONTEXT_ARTIFACTS = 3
TRANSFORM_TOOLS = frozenset({"transform", "llm_transform"})


class OrchestratorError(Exception):
    pass


class InputError(OrchestratorError):
    pass


class PlanItem(BaseModel):
    step: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    instruction: str | None = None
    on_error_skip: bool = False


class RunResult(BaseModel):
    run_id: str
    status: str
    partial: bool
    report_path: str
    ledger_path: str
    skipped_steps: list[dict[str, Any]] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)


def normalize_domain(value: str) -> str:
    text = value.strip().lower()
    if "://" in text:
        text = urlparse(text).netloc
    text = text.split("/")[0].split("?")[0].split("#")[0]
    if text.startswith("www."):
        text = text[4:]
    if not text or "." not in text:
        raise InputError(f"'{value}' is not a valid domain")
    return text


def build_brief(runbook: Runbook, inputs: dict[str, Any]) -> dict[str, Any]:
    brief: dict[str, Any] = {}
    for spec in runbook.meta.inputs:
        value = inputs.get(spec.name)
        if value is None or value == "":
            if spec.required:
                raise InputError(f"missing required input '{spec.name}' ({spec.doc or ''})".strip())
            continue
        brief[spec.name] = _coerce_input(spec, value)
    unknown = set(inputs) - {spec.name for spec in runbook.meta.inputs}
    if unknown:
        raise InputError(
            f"unknown inputs {sorted(unknown)}; runbook '{runbook.name}' accepts: "
            + ", ".join(spec.name for spec in runbook.meta.inputs)
        )
    return brief


def _coerce_input(spec: RunbookInput, value: Any) -> Any:
    if spec.type == "domain":
        if not isinstance(value, str):
            raise InputError(f"input '{spec.name}' must be a domain string")
        return normalize_domain(value)
    if spec.type == "list[domain]":
        if isinstance(value, str):
            items = [part.strip() for part in value.split(",") if part.strip()]
        elif isinstance(value, (list, tuple)):
            items = [str(part) for part in value]
        else:
            raise InputError(f"input '{spec.name}' must be a list of domains")
        domains = [normalize_domain(item) for item in items]
        if spec.max is not None and len(domains) > spec.max:
            raise InputError(
                f"input '{spec.name}' accepts at most {spec.max} domains, got {len(domains)}"
            )
        if spec.required and not domains:
            raise InputError(f"input '{spec.name}' must not be empty")
        return domains
    if not isinstance(value, str):
        raise InputError(f"input '{spec.name}' must be a string")
    return value.strip()


def validate_plan(
    plan: list[dict[str, Any]],
    allowlist: list[str],
    catalog: list[str],
) -> list[PlanItem]:
    allowed = set(allowlist)
    live = set(catalog)
    valid: list[PlanItem] = []
    for index, raw in enumerate(plan):
        try:
            item = PlanItem.model_validate(raw)
        except Exception as exc:
            log.warning("plan item %d dropped: not a valid plan item: %s", index, exc)
            continue
        if item.tool.lower() in TRANSFORM_TOOLS:
            valid.append(item)
            continue
        if item.tool not in allowed:
            log.warning(
                "plan item %d dropped: tool '%s' is not in the runbook allowlist",
                index, item.tool,
            )
            continue
        if item.tool not in live:
            log.warning(
                "plan item %d dropped: tool '%s' not in live catalog (retired or renamed)",
                index, item.tool,
            )
            continue
        valid.append(item)
    return valid


_PLAN_INSTRUCTIONS = """\
You are the planner for a research run. Produce an ordered execution plan as JSON:
{"plan": [{"step": "<short name>", "tool": "<tool name>", "arguments": {...}, "on_error_skip": true|false}]}

Rules:
- Use ONLY tools from the allowlisted catalog below, with arguments matching each
  tool's schema exactly.
- Follow the runbook sequence; skip steps the brief makes unnecessary (e.g. skip
  discovery when competitors are named).
- Set on_error_skip=true for enrichment steps that may safely fail.
- Transform steps are first-class: use {"step": "<name>", "tool": "transform",
  "instruction": "<what to synthesize, and from which prior steps>"} for the
  runbook's Transform: markers (synthesis/extraction between tool calls). They
  need no tool schema and do not consume the tool-call budget.
- Prefer one batched tool call over per-item fan-out when the tool supports bulk
  input (e.g. dataforseo_bl_bulk_ranks takes multiple domains in one call).
- Keep the total number of tool-call steps within the tool-call budget.
"""


class Orchestrator:
    def __init__(
        self,
        prowl: ProwlClient,
        llm: LLMClient,
        runs_root: Path | str = "runs",
    ) -> None:
        self.prowl = prowl
        self.llm = llm
        self.runs_root = Path(runs_root)

    async def run(
        self,
        runbook_name: str,
        inputs: dict[str, Any],
        run_id: str | None = None,
    ) -> RunResult:
        runbook = get_runbook(runbook_name)
        brief = build_brief(runbook, inputs)
        run_id = run_id or self._new_run_id(runbook_name)
        store = ArtifactStore(self.runs_root / run_id)
        ledger = Ledger.load(store.run_dir / "ledger.json")
        checkpoint = store.load_checkpoint()
        if checkpoint is not None and checkpoint.runbook != runbook_name:
            raise OrchestratorError(
                f"run {run_id} already belongs to runbook '{checkpoint.runbook}'"
            )
        resuming = checkpoint is not None and checkpoint.status == "running" and checkpoint.plan
        if resuming:
            log.info("resuming run %s after step %s", run_id, checkpoint.completed_steps[-1] if checkpoint.completed_steps else -1)
        else:
            checkpoint = Checkpoint(run_id=run_id, runbook=runbook_name, brief=brief)
        started_monotonic = time.monotonic()

        catalog = await self.prowl.list_tools()

        if not resuming:
            plan = await self._plan(runbook, brief, catalog)
            checkpoint.plan = [item.model_dump() for item in plan]
            store.save_checkpoint(checkpoint)

        plan = validate_plan(checkpoint.plan, runbook.meta.tools, catalog)
        await self._execute(runbook, checkpoint, plan, store, ledger, started_monotonic)

        outcome, fidelity = await produce_report(
            self.llm, runbook, ledger, brief,
            partial=checkpoint.partial, skipped_steps=checkpoint.skipped_steps,
            transform_notes=checkpoint.transform_notes,
        )

        report_path = store.run_dir / "report.md"
        report_path.write_text(outcome.report_md, encoding="utf-8")
        ledger.save()
        checkpoint.status = "partial" if checkpoint.partial else "complete"
        stats = {
            "data_calls": checkpoint.counters.get("data_calls", 0),
            "total_calls": self.prowl.calls_made,
            "cost_usd": checkpoint.counters.get("cost_usd"),
            "claims": len(ledger.claims),
            "duration_s": round(time.monotonic() - started_monotonic, 1),
            "lint_issues": outcome.lint_after,
            "lint_issues_before": outcome.lint_before,
            "lint_issues_after": outcome.lint_after,
            "lint_repair_passes": outcome.repair_passes,
            "citation_fidelity": fidelity.stats,
        }
        checkpoint.stats = stats
        store.save_checkpoint(checkpoint)
        self._export_html(store.run_dir)

        return RunResult(
            run_id=run_id,
            status=checkpoint.status,
            partial=checkpoint.partial,
            report_path=str(report_path),
            ledger_path=str(ledger.path),
            skipped_steps=checkpoint.skipped_steps,
            stats=stats,
        )

    @staticmethod
    def _export_html(run_dir: Path) -> None:
        try:
            from research_agent.report.render import render_run

            render_run(run_dir)
        except Exception as exc:
            log.warning("HTML export failed for %s: %s", run_dir, exc)

    async def _plan(
        self, runbook: Runbook, brief: dict[str, Any], catalog: list[str]
    ) -> list[PlanItem]:
        schemas = await self._tool_schemas(runbook.meta.tools, catalog)
        budget = runbook.meta.budget
        user = (
            f"## Brief (run inputs)\n{json.dumps(brief, indent=2)}\n\n"
            f"## Budget\nmax_tool_calls={budget.max_tool_calls}, "
            f"max_usd={budget.max_usd}, max_minutes={budget.max_minutes}\n\n"
            f"## Allowlisted tool schemas (live catalog)\n{json.dumps(schemas, indent=2, default=str)}\n\n"
            "Output the plan JSON now."
        )
        text = await self.llm.complete(
            [
                {"role": "system", "content": runbook.body + "\n\n" + _PLAN_INSTRUCTIONS},
                {"role": "user", "content": user},
            ],
            tier="strong",
            json_mode=True,
            max_tokens=8000,
        )
        payload = _parse_json_object(text)
        raw_plan = payload.get("plan") if isinstance(payload, dict) else None
        if not isinstance(raw_plan, list):
            raise OrchestratorError("planner did not return a JSON object with a 'plan' list")
        plan = validate_plan(raw_plan, runbook.meta.tools, catalog)
        if not plan:
            raise OrchestratorError("planner produced no executable steps after validation")
        return plan

    async def _tool_schemas(self, tools: list[str], catalog: list[str]) -> dict[str, Any]:
        live = set(catalog)
        names = [name for name in tools if name in live]
        results = await asyncio.gather(
            *(self._safe_tool_info(name) for name in names)
        )
        return {name: schema for name, schema in zip(names, results) if schema is not None}

    async def _safe_tool_info(self, name: str) -> Any:
        try:
            return await self.prowl.tool_info(name)
        except ProwlError as exc:
            log.warning("tool_info(%s) failed: %s", name, exc)
            return None

    async def _execute(
        self,
        runbook: Runbook,
        checkpoint: Checkpoint,
        plan: list[PlanItem],
        store: ArtifactStore,
        ledger: Ledger,
        started_monotonic: float,
    ) -> None:
        budget = runbook.meta.budget
        completed = set(checkpoint.completed_steps)
        cost_advisory_logged = False

        for index, item in enumerate(plan):
            if index in completed:
                continue

            stop_reason = self._budget_stop_reason(
                budget, checkpoint, started_monotonic
            )
            if stop_reason is None and self.prowl.cost_usd is None and not cost_advisory_logged:
                log.info(
                    "no cost metadata from server; max_usd=%.2f enforced only if cost info appears",
                    budget.max_usd,
                )
                cost_advisory_logged = True
            if stop_reason is not None:
                remaining = [
                    {"index": j, "step": plan[j].step, "tool": plan[j].tool, "reason": stop_reason}
                    for j in range(index, len(plan)) if j not in completed
                ]
                checkpoint.skipped_steps.extend(remaining)
                checkpoint.partial = True
                checkpoint.stop_reason = stop_reason
                log.warning("budget exhausted (%s); skipping %d steps", stop_reason, len(remaining))
                break

            log.info("step %d/%d: %s (%s)", index + 1, len(plan), item.step, item.tool)
            is_transform = item.tool.lower() in TRANSFORM_TOOLS
            try:
                if is_transform:
                    result = await self._run_transform(item, store)
                else:
                    result = await self.prowl.call_tool(item.tool, item.arguments)
            except Exception as exc:
                if item.on_error_skip:
                    log.warning("step %d failed (on_error_skip): %s", index, exc)
                    checkpoint.skipped_steps.append(
                        {"index": index, "step": item.step, "tool": item.tool, "reason": str(exc)[:200]}
                    )
                    checkpoint.completed_steps.append(index)
                    store.save_checkpoint(checkpoint)
                    continue
                checkpoint.partial = True
                checkpoint.stop_reason = f"step '{item.step}' failed: {exc}"
                checkpoint.skipped_steps.extend(
                    {"index": j, "step": plan[j].step, "tool": plan[j].tool, "reason": checkpoint.stop_reason}
                    for j in range(index, len(plan)) if j not in completed
                )
                log.error("step %d failed, aborting to writer: %s", index, exc)
                break

            if is_transform:
                raw_path = store.save_markdown(index, "transform", str(result))
                checkpoint.transform_notes.append(str(result))
            else:
                checkpoint.counters["data_calls"] = checkpoint.counters.get("data_calls", 0) + 1
                if self.prowl.cost_usd is not None:
                    checkpoint.counters["cost_usd"] = self.prowl.cost_usd
                raw_path = store.save_raw(index, item.tool, result)
            try:
                await self._extract_claims(item, result, raw_path, ledger)
            except Exception as exc:
                log.warning("claim extraction failed for step %d: %s", index, exc)
            ledger.save()

            checkpoint.completed_steps.append(index)
            store.save_checkpoint(checkpoint)

    async def _run_transform(self, item: PlanItem, store: ArtifactStore) -> str:
        instruction = item.instruction or (
            json.dumps(item.arguments, ensure_ascii=False) if item.arguments else item.step
        )
        context_parts = []
        for path in store.raw_files()[-_TRANSFORM_CONTEXT_ARTIFACTS:]:
            snippet = path.read_text(encoding="utf-8")[:_TRANSFORM_CONTEXT_CHARS]
            context_parts.append(f"### {path.name}\n{snippet}")
        system = (
            "You are a transform step in a research run: you synthesize and extract "
            "from prior raw tool artifacts. Produce concise markdown notes answering "
            "the instruction, using ONLY facts present in the provided artifacts — "
            "no outside knowledge, no invented numbers. Keep values attached to "
            "their units and name the artifact each fact came from."
        )
        user = (
            f"## Instruction\n{instruction}\n\n"
            "## Recent raw artifacts\n"
            + ("\n\n".join(context_parts) if context_parts else "(no artifacts yet)")
        )
        return await self.llm.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            tier="cheap",
            max_tokens=2000,
        )

    def _budget_stop_reason(
        self, budget: Any, checkpoint: Checkpoint, started_monotonic: float
    ) -> str | None:
        if checkpoint.counters.get("data_calls", 0) >= budget.max_tool_calls:
            return f"max_tool_calls={budget.max_tool_calls}"
        elapsed_minutes = (time.monotonic() - started_monotonic) / 60
        if elapsed_minutes >= budget.max_minutes:
            return f"max_minutes={budget.max_minutes}"
        cost = self.prowl.cost_usd
        if cost is not None and cost >= budget.max_usd:
            return f"max_usd={budget.max_usd}"
        return None

    async def _extract_claims(
        self, item: PlanItem, result: Any, raw_path: Path, ledger: Ledger
    ) -> None:
        raw_text = json.dumps(result, ensure_ascii=False, default=str)[:_RAW_SNIPPET_CHARS]
        system = (
            "You extract evidence-ledger claims from a raw tool result. Output JSON: "
            '{"claims": [{"claim": "...", "subject": "...", "value": "...", "unit": "...", '
            '"source_url": "...", "verbatim": true|false}]}. '
            "Include ONLY facts present in the raw text — no outside knowledge. "
            "Each claim needs either a verbatim quote (verbatim=true) or a value+unit. "
            "'subject' is a short stable key grouping claims about the same metric "
            "(e.g. 'example.com monthly organic traffic'). Return at most 8 claims; "
            "prefer numbers and quotable findings. If nothing is extractable, return "
            '{"claims": []}.'
        )
        user = f"Tool: {item.tool}\nStep: {item.step}\nRaw result:\n{raw_text}"
        text = await self.llm.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            tier="cheap",
            json_mode=True,
            max_tokens=2000,
        )
        payload = _parse_json_object(text)
        claims = payload.get("claims", []) if isinstance(payload, dict) else []
        for raw_claim in claims[:8]:
            if not isinstance(raw_claim, dict) or not raw_claim.get("claim"):
                continue
            ledger.add(
                claim=str(raw_claim["claim"]),
                value=raw_claim.get("value"),
                unit=raw_claim.get("unit"),
                subject=raw_claim.get("subject"),
                source_tool=item.tool,
                source_url=raw_claim.get("source_url"),
                raw_ref=str(raw_path),
                verbatim=bool(raw_claim.get("verbatim")),
            )

    @staticmethod
    def _new_run_id(runbook_name: str) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"{stamp}-{runbook_name}-{uuid.uuid4().hex[:6]}"


def _parse_json_object(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {}
