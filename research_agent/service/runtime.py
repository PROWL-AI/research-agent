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

from research_agent.agent import tool_limits
from research_agent.evidence.store import ArtifactStore
from research_agent.evidence.ledger import Ledger
from research_agent.agent.orchestrator import Orchestrator, build_brief
from research_agent.config import Config, ConfigError, resolve_llm_cap
from research_agent.service.delegation import require_owner
from research_agent.llm import LLMClient, LLMError
from research_agent.prowl_client import ProwlClient, ToolCallError
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
            refused.stops_run = True  # every later call hits the same limit
            raise refused
        try:
            call = self.store.start_call(self.job["id"], "tool", arguments.get("tool_name", prowl_tool), scrub(arguments.get("params", {})))
        except Exception as exc:  # noqa: BLE001 — journal unavailable: do not dispatch
            refused = ToolCallError(f"Call journal unavailable ({type(exc).__name__}); nothing was sent")
            refused.cost_usd = 0.0
            refused.stops_run = True  # nothing can be journaled, so nothing is sent
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

    def _before_send(self):
        # Before the run's meter records an attempt: a refusal here sent
        # nothing and costs nothing, in the journal and the run ledger alike.
        if len(self.store.calls(self.job["id"])) >= 256:
            raise LLMError("Service call limit reached (256); nothing was sent", retryable=False)

    async def _post(self, payload, request_kwargs):
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
    if not isinstance(request, dict) or set(request) - {"kind", "runbook", "inputs", "tool", "params", "context",
                                                         "max_llm_usd", "resumeJobId"}:
        raise ValueError("Request fields: kind, runbook, inputs, tool, params, context, max_llm_usd, resumeJobId")
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
        if isinstance(request.get("max_llm_usd"), bool):
            raise ValueError("max_llm_usd must be a number")
        try:
            # The caller's cap and the service's RESEARCH_MAX_LLM_USD are checked
            # here, before an approvable job exists (the stdio surface does the same).
            resolve_llm_cap(request.get("max_llm_usd"), None, None)
        except ConfigError as exc:
            raise ValueError(str(exc)) from exc
        if "resumeJobId" in request and (not isinstance(request["resumeJobId"], str)
                                         or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", request["resumeJobId"])):
            raise ValueError("resumeJobId must be a job id")
    elif {"max_llm_usd", "resumeJobId"} & set(request):
        raise ValueError("max_llm_usd and resumeJobId apply to research requests only")
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


class LimitRefused(ValueError):
    """A known provider limit refused the request; nothing was sent (B-071)."""


def refuse_known_limits(request):
    """B-071 on the direct path: research.tools.call refuses a value the provider is known
    to refuse (agent/tool_limits.py) before a job exists, rather than have it billed. Its
    caller writes the params on purpose, so template text is not judged here (B-070 guards
    planned steps). Checked after an idempotent replay, which answers its job as before."""
    if request.get("kind") == "tool":
        broken = tool_limits.refused(request["tool"], request["params"])
        if broken:
            raise LimitRefused(f"{request['tool']} does not take {', '.join(broken)} (a known provider limit)")


class Runtime:
    def __init__(self, store: Store):
        self.store = store
        manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
        self.producer = {k: manifest["provider"][k] for k in ("id", "revision", "contentHash")}
        self.tasks = {}
        self.stopping = False

    def create(self, request, key, trace=None, delegation=None, via="mcp"):
        if self.stopping:
            raise Conflict("Service is stopping")
        if not isinstance(key, str) or not 1 <= len(key) <= 128:
            raise ValueError("idempotencyKey must contain 1–128 characters")
        request = validate_request(request)
        # A replay answers the job it created before any rule is checked again:
        # a resume's own job would otherwise count as "already continuing" it.
        existing = self.store.replay(request, key, delegation)
        if existing is not None:
            return existing
        refuse_known_limits(request)
        run_dir = chain_owner = None
        if request.get("resumeJobId"):
            run_dir = self._check_resumable(request, delegation)
            previous = self.store.job(request["resumeJobId"])
            # Who owns the chain: the principal of its first delegated job. An
            # operator's resume stays the operator's act (delegation None) and
            # stays visible to that agent through chainOwner.
            chain_owner = previous.get("chainOwner") or previous.get("delegation")
        if request["kind"] != "tutorial":
            try:
                Config.from_env(require_llm=request["kind"] == "research")
            except ConfigError as exc:
                raise ValueError("Provider credentials are not connected. Use the tutorial or configure the supervised service through Observatory.") from exc
        return self.store.create(request, key, child_trace(trace), delegation=delegation, run_dir=run_dir, via=via,
                                 chain_owner=chain_owner)[0]

    def _check_resumable(self, request, delegation=None):
        """B-039: a resume continues an ENDED, unfinished research job's run and
        answers the run directory it continues — the root of a chain of resumes,
        never a new one. Refused: another principal's job, another runbook, other
        inputs than the run's (the operator approves what will run), a job the
        operator rejected, a finished run, a run another resume already holds."""
        try:
            previous = self.store.job(request["resumeJobId"])
        except Exception as exc:  # noqa: BLE001 — unknown id
            raise ValueError("resumeJobId names no job of this service") from exc
        require_owner(previous, delegation)
        if previous["request"].get("kind") != "research":
            raise ValueError("resumeJobId must name a research job")
        if previous["request"].get("runbook") != request["runbook"]:
            raise ValueError("resumeJobId belongs to another runbook")
        if previous["request"].get("inputs") != request["inputs"]:
            raise ValueError("a resume continues the run's own inputs; send them unchanged (a new run takes new inputs)")
        if previous.get("phase") == "rejected":
            raise ValueError(f"job {previous['id']} was rejected by the operator; nothing ran to continue")
        run_dir = run_dir_name(previous)
        if previous["status"] in {"input_required", "working"}:
            raise ValueError(f"job {previous['id']} is {previous['status']}; only an ended job can be resumed")
        if previous["status"] == "completed":
            checkpoint = ArtifactStore(self.store.root / "runs" / run_dir).load_checkpoint()
            if checkpoint is None or checkpoint.status == "complete":
                raise ValueError(f"job {previous['id']} finished its run; nothing is left to continue")
        for other in self.store.jobs():
            if other["status"] in {"input_required", "working"} and run_dir_name(other) == run_dir:
                raise ValueError(f"run {run_dir} is already being continued by job {other['id']}")
        return run_dir

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
        except LimitRefused as exc:
            # Refused at dispatch (a job created before the limit was known): nothing was
            # sent, so the reader gets the reason rather than "inspect call receipts".
            self.store.transition(job_id, "failed", "failed", error={"code": "request-rejected", "message": str(exc)[:300]})
        except Exception as exc:
            self.store.transition(job_id, "failed", "failed", error=self._with_terminal(job_id, {"code": "execution-failed", "message": type(exc).__name__ + ": inspect call receipts and provider health; no automatic retry."}))

    def _with_terminal(self, job_id, error):
        """A research job's error carries the run checkpoint's terminal_code, so the
        job view and research.artifact.get name the same outcome (docs/FABRIC.md,
        "Job phase and run terminal state")."""
        try:
            checkpoint = ArtifactStore(self.store.root / "runs" / run_dir_name(self.store.job(job_id))).load_checkpoint()
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
        if req["kind"] == "tool":
            # Checked again at dispatch, before any connection: a job created before a limit was
            # known may wait for approval.
            refuse_known_limits(req)
        async with ObservedProwl(cfg.prowl_api_key, cfg.prowl_mcp_url).observe(self.store, job) as prowl:
            if req["kind"] == "tool":
                params = tool_limits.canonical(req["tool"], req["params"])
                result = await prowl.call_tool(req["tool"], params, idempotency_key=job["id"])
                clean = scrub(result)
                encoded = json.dumps(clean, ensure_ascii=False)
                if len(encoded.encode()) > 8_000_000:
                    raise ValueError("Tool artifact exceeds 8 MB local limit; call receipt retained")
                from research_agent.evidence.ledger import _atomic_write_text
                folder = self.store.root / "runs" / job["id"]
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                _atomic_write_text(folder / "result.json", encoded)
                out = {"data": bounded(clean), "artifact": "result.json", "quality": "provider response; not independently verified"}
                coverage = tool_limits.statements([req["tool"]])
                if coverage:
                    out["coverage"] = coverage
                return out
            async with ObservedLLM(cfg.llm_base_url, cfg.llm_api_key, cfg.llm_model, cfg.llm_model_strong).observe(self.store, job) as llm:
                orch = Orchestrator(prowl, llm, self.store.root / "runs", max_workers=settings["max_workers"])
                # A resume runs on the earlier job's run directory: its saved raw,
                # attempt ledger and recorded cap carry over (B-039).
                run_id = run_dir_name(job)
                result = await orch.run(req["runbook"], req["inputs"], run_id=run_id,
                                        max_llm_usd=req.get("max_llm_usd"))
                folder = self.store.root / "runs" / run_id
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
                    "proof": [], "scope": scope, "notVerified": [attribution_gap(job),
                    {"claim": "Research claims", "reason": output.get("quality", "not independently verified")},
                    *({"claim": "Source coverage", "reason": note} for note in output.get("coverage", []))],
                    "artifacts": [], "createdAt": now(), "producer": producer, "output": output, "usage": usage}
        if job.get("traceparent"):
            envelope["trace"] = {"traceparent": job["traceparent"]}
        return envelope


def attribution_gap(job):
    """What the envelope cannot vouch for about who asked. A verified delegation
    (DEC-0039) proves the principal and the caller; a hub binding is still not
    presented, so admission stays unverified either way."""
    if job.get("delegation"):
        return {"claim": "Fabric admission", "reason": "The delegation token was verified offline and its principal and "
                "caller recorded; no hub binding receipt was presented"}
    return {"claim": "Fabric admission and chain attribution", "reason": "Caller-declared context is not a verified hub binding"}


def run_dir_name(job):
    """The run directory a job writes: its own id, or — for a resume (B-039) —
    the root run of the chain it continues, fixed when the resume was created.
    A resume stored before `runDir` existed falls back to the job it names."""
    return job.get("runDir") or (job.get("request") or {}).get("resumeJobId") or job["id"]


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
