"""Observed execution using the existing Orchestrator; no automatic paid retries."""
from __future__ import annotations

import asyncio
import json
import math
import re
import secrets
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from research_agent.evidence.store import ArtifactStore
from research_agent.evidence.ledger import Ledger
from research_agent.agent.orchestrator import Orchestrator, build_brief
from research_agent.config import Config, ConfigError
from research_agent.llm import LLMClient, LLMError
from research_agent.prowl_client import ProwlClient, ProwlError, ToolCallError, _call_timeout
from research_agent.runbook import get_runbook, list_runbooks
from .store import Store, Conflict, digest, now

SECRET = re.compile(r"(?i)(authorization|password|api[_-]?key|access[_-]?token|secret|cookie)")
TRACE = re.compile(r"^(?!ff)[a-f0-9]{2}-(?!0{32}-)[a-f0-9]{32}-(?!0{16}-)[a-f0-9]{16}-[a-f0-9]{2}$")


def scrub(value):
    if isinstance(value, dict):
        return {k: "[redacted]" if SECRET.search(str(k)) else scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def child_trace(parent):
    if parent is None:
        return None
    if not isinstance(parent, str) or not TRACE.fullmatch(parent):
        raise ValueError("Invalid traceparent")
    p = parent.split("-")
    return "-".join([p[0], p[1], secrets.token_hex(8), p[3]])


def money(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


class ObservedProwl(ProwlClient):
    def observe(self, store, job):
        self.store, self.job = store, job
        return self

    def _call_meta(self):
        # The core's _rpc keeps its retry and reconnect for metadata calls; a
        # paid prowl_call_tool is still one attempt per idempotency key there
        # (a lost reply is not permission to pay again) — B-004.
        trace = child_trace(self.job.get("traceparent"))
        return {"traceparent": trace} if trace else None

    async def _invoke(self, prowl_tool, arguments, *, record=None):
        # Metadata lookups are observable but excluded from paid usage receipts.
        if prowl_tool != "prowl_call_tool":
            return await super()._invoke(prowl_tool, arguments, record=record)
        # Local refusals before anything is sent are definite (and free): a
        # resume must not treat them as calls that may have been charged.
        if len(self.store.calls(self.job["id"])) >= 256:
            refused = ToolCallError("Service call limit reached (256); nothing was sent")
            refused.cost_usd = 0.0
            raise refused
        try:
            call = self.store.start_call(self.job["id"], "tool", arguments.get("tool_name", prowl_tool), scrub(arguments.get("params", {})))
        except Exception as exc:  # noqa: BLE001 — journal unavailable: do not dispatch
            refused = ToolCallError(f"Call journal unavailable ({type(exc).__name__}); nothing was sent")
            refused.cost_usd = 0.0
            raise refused from exc
        start = time.monotonic()
        index = len(self.call_log)
        result, status = None, "failed"
        try:
            result = await super()._invoke(prowl_tool, arguments, record=record)
            status = "completed"
            return result
        except asyncio.CancelledError:
            status = "unknown"
            raise
        finally:
            # The record is allocated before dispatch and receives billed failure costs too.
            receipt = self.call_log[index] if len(self.call_log) > index else None
            cost = money(receipt.cost_usd) if receipt else None
            self.store.finish_call(call, status=status, durationMs=int((time.monotonic()-start)*1000),
                                   costUsd=cost, costBasis="provider" if cost is not None else "unknown",
                                   output=bounded(scrub(result)))


class ObservedLLM(LLMClient):
    """Journals each HTTP attempt of the core client (retries included) and adds
    trace headers. Retries, Retry-After, the max_tokens-scaled read timeout and
    LLMError mapping are LLMClient's own — one transport (B-003)."""

    def observe(self, store, job):
        self.store, self.job = store, job
        return self

    async def _post(self, payload, request_kwargs):
        if len(self.store.calls(self.job["id"])) >= 256:
            raise LLMError("Service call limit reached (256)", retryable=False)
        call = self.store.start_call(self.job["id"], "llm", payload["model"],
                                    {"messages": len(payload["messages"]), "max_tokens": payload.get("max_tokens")})
        trace = child_trace(self.job.get("traceparent"))
        kwargs = dict(request_kwargs)
        if trace:
            kwargs["headers"] = {**kwargs.get("headers", {}), "traceparent": trace}
        start, fields = time.monotonic(), {"status": "failed"}
        try:
            response = await super()._post(payload, kwargs)
            try:
                data = response.json() or {}
            except ValueError:
                data = {}
            usage = (data.get("usage") or {}) if isinstance(data, dict) else {}
            cost = money(usage.get("cost"))
            fields.update(costUsd=cost, costBasis="provider" if cost is not None else "unknown",
                          inputTokens=max(0, int(usage.get("prompt_tokens") or 0)),
                          outputTokens=max(0, int(usage.get("completion_tokens") or 0)))
            if response.status_code < 400:
                try:
                    self._extract(data)  # a truncated or empty completion is a failed call
                    fields["status"] = "completed"
                except LLMError:
                    pass
            return response
        except asyncio.CancelledError:
            fields["status"] = "unknown"
            raise
        finally:
            self.store.finish_call(call, durationMs=int((time.monotonic()-start)*1000), **fields)


def bounded(value, limit=64000):
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    return value if len(encoded) <= limit else {"truncated": True, "preview": encoded[:limit], "reason": "Inline preview limit; research raw artifacts are available separately."}


def validate_request(request):
    if not isinstance(request, dict) or set(request) - {"kind", "runbook", "inputs", "tool", "params", "context"}:
        raise ValueError("Request fields: kind, runbook, inputs, tool, params, context")
    kind = request.get("kind")
    if kind not in {"research", "tool", "tutorial"}:
        raise ValueError("kind must be research, tool or tutorial")
    context = request.get("context", {})
    if not isinstance(context, dict) or set(context) - {"requester", "chain", "project", "node", "parent"}:
        raise ValueError("Invalid chain context")
    if any(not isinstance(v, str) or len(v) > 256 for v in context.values()):
        raise ValueError("Context values must be strings up to 256 characters")
    if kind == "research":
        if not isinstance(request.get("runbook"), str) or not isinstance(request.get("inputs"), dict):
            raise ValueError("research requires runbook and inputs")
        build_brief(get_runbook(request["runbook"]), request["inputs"])
    if kind == "tool":
        if not isinstance(request.get("tool"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", request["tool"]):
            raise ValueError("Invalid tool name")
        if not isinstance(request.get("params"), dict):
            raise ValueError("params must be an object")
    if len(json.dumps(request)) > 64000:
        raise ValueError("Request exceeds 64 KB")
    if scrub(request) != request:
        raise ValueError("Credentials belong in the service environment, not request arguments")
    return request


class Runtime:
    def __init__(self, store: Store):
        self.store = store
        manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
        self.producer = {k: manifest["provider"][k] for k in ("id", "revision", "contentHash")}
        self.tasks = {}
        self.stopping = False

    def create(self, request, key, trace=None):
        if self.stopping:
            raise Conflict("Service is stopping")
        if not isinstance(key, str) or not 1 <= len(key) <= 128:
            raise ValueError("idempotencyKey must contain 1–128 characters")
        request = validate_request(request)
        if request["kind"] != "tutorial":
            try:
                Config.from_env(require_llm=request["kind"] == "research")
            except ConfigError as exc:
                raise ValueError("Provider credentials are not connected. Use the tutorial or configure the supervised service through Observatory.") from exc
        return self.store.create(request, key, child_trace(trace))[0]

    def decide(self, job_id, proposal_digest, approve):
        job = self.store.decide(job_id, proposal_digest, approve)
        if approve:
            task = asyncio.create_task(self.execute(job_id), name=job_id)
            self.tasks[job_id] = task
            task.add_done_callback(lambda _: self.tasks.pop(job_id, None))
        return job

    def cancel(self, job_id):
        job = self.store.transition(job_id, "cancelled", "cancelled")
        if job_id in self.tasks:
            self.tasks[job_id].cancel()
        return job

    async def close(self):
        self.stopping = True
        for task in list(self.tasks.values()):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)

    async def execute(self, job_id):
        start = time.monotonic()
        try:
            # Admission to execution is FIFO by creation time. Queue wait counts toward deadline.
            initial = self.store.job(job_id)
            async with asyncio.timeout(initial["config"]["timeout_minutes"] * 60):
                while True:
                    working = [j for j in self.store.jobs() if j["status"] == "working"]
                    active = sum(j["phase"] == "executing" for j in working)
                    queued = sorted([j for j in working if j["phase"] == "queued"], key=lambda j: j["createdAt"])
                    if queued and queued[0]["id"] == job_id and active < self.store.config()["parallel_jobs"]:
                        break
                    await asyncio.sleep(.2)
                job = self.store.transition(job_id, "working", "executing")
                if job["status"] != "working":
                    return
                if job["request"]["kind"] == "tutorial":
                    output = await self.tutorial(job)
                else:
                    output = await self.live(job)
                envelope = self.envelope(job, output, int((time.monotonic()-start)*1000))
                self.store.transition(job_id, "completed", "completed", result=envelope)
        except asyncio.CancelledError:
            if self.store.job(job_id)["status"] == "working":
                self.store.transition(job_id, "failed", "interrupted", error=self._with_terminal(job_id, {"code": "interrupted", "message": "Execution interrupted; upstream outcome may be unknown. No automatic retry."}))
            raise
        except TimeoutError:
            self.store.transition(job_id, "failed", "failed", error=self._with_terminal(job_id, {"code": "timeout", "message": "Wall-clock timeout reached; gathered evidence stays in the run checkpoint. No automatic retry."}))
        except Exception as exc:
            self.store.transition(job_id, "failed", "failed", error=self._with_terminal(job_id, {"code": "execution-failed", "message": type(exc).__name__ + ": inspect call receipts and provider health; no automatic retry."}))

    def _with_terminal(self, job_id, error):
        """A research job's error carries the run checkpoint's terminal_code, so the
        job view and research.artifact.get name the same outcome (docs/FABRIC.md,
        "Job phase and run terminal state")."""
        try:
            checkpoint = ArtifactStore(self.store.root / "runs" / job_id).load_checkpoint()
        except (ValueError, OSError):
            checkpoint = None
        if checkpoint is not None and checkpoint.terminal_code:
            error = {**error, "terminalCode": checkpoint.terminal_code}
        return error

    async def tutorial(self, job):
        rows = [{"domain": "example.org", "visits": 12800, "change_pct": 8.4},
                {"domain": "example.net", "visits": 9600, "change_pct": -2.1},
                {"domain": "example.com", "visits": 18400, "change_pct": 12.6}]
        for name in ["sample.traffic", "sample.sources", "sample.summary"]:
            call = self.store.start_call(job["id"], "tool", name, {"fixture": True})
            try:
                await asyncio.sleep(.2)
            except asyncio.CancelledError:
                self.store.finish_call(call, status="cancelled", costUsd=0.0, costBasis="fixture")
                raise
            self.store.finish_call(call, status="completed", durationMs=200, output=rows,
                                   costUsd=0.0, costBasis="fixture")
        return {"tutorial": True, "rows": rows, "report": "Учебный отчёт\n\nТри вымышленных домена сравниваются по вымышленному трафику. example.com имеет наибольшее значение в этом примере. Эти числа нельзя использовать для решения о рынке.\n\nВ реальном запросе здесь появятся отчёт, источники и история вызовов.",
                "sources": [{"label": "Локальный учебный набор", "verification": "synthetic"}],
                "quality": "synthetic — not research evidence"}

    async def live(self, job):
        req, settings = job["request"], job["config"]
        cfg = replace(Config.from_env(require_llm=req["kind"] == "research"),
                      llm_model=settings["cheap_model"], llm_model_strong=settings["strong_model"])
        async with ObservedProwl(cfg.prowl_api_key, cfg.prowl_mcp_url).observe(self.store, job) as prowl:
            if req["kind"] == "tool":
                result = await prowl.call_tool(req["tool"], req["params"], idempotency_key=job["id"])
                clean = scrub(result)
                encoded = json.dumps(clean, ensure_ascii=False)
                if len(encoded.encode()) > 8_000_000:
                    raise ValueError("Tool artifact exceeds 8 MB local limit; call receipt retained")
                from research_agent.evidence.ledger import _atomic_write_text
                folder = self.store.root / "runs" / job["id"]
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                _atomic_write_text(folder / "result.json", encoded)
                return {"data": bounded(clean), "artifact": "result.json", "quality": "provider response; not independently verified"}
            async with ObservedLLM(cfg.llm_base_url, cfg.llm_api_key, cfg.llm_model, cfg.llm_model_strong).observe(self.store, job) as llm:
                orch = Orchestrator(prowl, llm, self.store.root / "runs", max_workers=settings["max_workers"])
                result = await orch.run(req["runbook"], req["inputs"], run_id=job["id"])
                folder = self.store.root / "runs" / job["id"]
                return {"research": result.model_dump(), "report": (folder / "report.md").read_text()[:200000],
                        # The compact view inline; the whole schema-2 ledger (quotes,
                        # spans, source identity) is the ledger.json artifact (B-036).
                        "ledger": bounded(scrub({"claims": Ledger.load(folder / "ledger.json").compact_rows()})),
                        "ledgerArtifact": "ledger.json",
                        "quality": "ledger statuses follow evidence rules v2, tested offline only; live acceptance pending (wave 6)"}

    def envelope(self, job, output, wall_ms):
        calls = self.store.calls(job["id"])
        usage = {"inputTokens": sum(c["inputTokens"] for c in calls), "outputTokens": sum(c["outputTokens"] for c in calls), "wallMs": wall_ms}
        if calls and all(c["costUsd"] is not None for c in calls):
            usage["costUsd"] = sum(c["costUsd"] for c in calls)
        producer = self.producer
        # Local scope is explicitly not a Fabric admission/binding receipt.
        scope = {"project": "urn:prowl:local", "run": "urn:prowl:job:" + job["id"], "node": "urn:prowl:node:local",
                 "binding": {"id": "urn:prowl:binding:unverified-local", "revision": 1, "contentHash": "sha256:" + digest(job["request"].get("context", {}))}, "writeScopes": []}
        outcome, statement = outcome_for(output)
        envelope = {"id": "urn:prowl:result:" + job["id"], "contractVersion": "0.1.0", "outcome": outcome,
                    "done": [{"claimId": "RUN_COMPLETED", "statement": statement}],
                    "proof": [], "scope": scope, "notVerified": [{"claim": "Fabric admission and chain attribution", "reason": "Caller-declared context is not a verified hub binding"},
                    {"claim": "Research claims", "reason": output.get("quality", "not independently verified")}],
                    "artifacts": [], "createdAt": now(), "producer": producer, "output": output, "usage": usage}
        if job.get("traceparent"):
            envelope["trace"] = {"traceparent": job["traceparent"]}
        return envelope


def outcome_for(output):
    """The envelope outcome from what the job produced (B-005; table in docs/FABRIC.md).

    A research job reports its run: `complete` → succeeded, `partial` → partial
    (the run's terminal_code says why). Tool and tutorial jobs that returned
    succeeded. Failed, cancelled and interrupted jobs never reach the envelope:
    they end with a typed job error instead."""
    research = output.get("research") if isinstance(output, dict) else None
    if isinstance(research, dict):
        status, code = research.get("status"), research.get("terminal_code")
        if status == "complete":
            return "succeeded", "Research run completed every planned step."
        return "partial", f"Research run ended partial (terminal_code={code}); the report discloses what is missing."
    return "succeeded", "Requested local execution completed; inspect output quality separately."


def runbooks():
    return [r.meta.model_dump() for r in list_runbooks()]
