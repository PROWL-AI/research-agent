"""Small dual-era JSON MCP surface, implemented from the public wire contract."""
from __future__ import annotations
import base64
import difflib
import json
import logging
from urllib.parse import quote
from jsonschema import Draft202012Validator
from . import costs, reports
from .delegation import Refused, recorded, refusal_tool_result, require_owner
from .runtime import child_trace, run_dir_name, runbooks
from .store import Conflict
from research_agent import __version__
from research_agent.agent import compact_mcp
from research_agent.events import emit
from .identity import SERVICE_ID, SERVICE_NAME

log = logging.getLogger(__name__)

VERSION = "2026-07-28"
SUPPORTED = [VERSION, "2025-11-25", "2025-06-18", "2025-03-26"]
META = "io.modelcontextprotocol/"
BASE = "https://prowl.chat/fabric/schemas/"


def obj(properties=None, required=None):
    return {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}


STRING = {"type": "string", "minLength": 1, "maxLength": 128}
CONTEXT = obj({k: {"type": "string", "maxLength": 256} for k in ["requester", "chain", "project", "node", "parent"]})
COMMON = {"idempotencyKey": STRING, "context": CONTEXT}
SCHEMAS = {
 "research.run": obj(dict(COMMON, runbook=STRING, inputs={"type": "object"},
                          max_llm_usd={"type": "number", "exclusiveMinimum": 0, "maximum": 1000,
                                       "description": "Cap on this run's own LLM spend (USD), checked before every LLM call; "
                                                      "unset: the service's RESEARCH_MAX_LLM_USD, the runbook's, else 5."},
                          resumeJobId={"type": "string", "minLength": 1, "maxLength": 128,
                                       "description": "Continue the run of an ended research job of the same runbook: "
                                                      "saved evidence is reused, nothing already paid is dispatched again."},
                          fresh={"type": "boolean",
                                 "description": "Organization keys: true starts a new paid run even when the organization "
                                                "already holds a ready report of the same runbook and inputs; unset, that "
                                                "report is answered (reused) and nothing is spent."}),
                     ["idempotencyKey", "runbook", "inputs"]),
 "research.tools.call": obj(dict(COMMON, tool=STRING, params={"type": "object"}), ["idempotencyKey", "tool", "params"]),
 "research.tutorial": obj(COMMON, ["idempotencyKey"]),
 "research.list_runbooks": obj(),
 "research.artifact.get": obj({"id": STRING, "name": STRING}, ["id", "name"]),
 "fabric.job.get": obj({"id": STRING, "inputResponses": {"type": "object"}}, ["id"]),
 "fabric.job.cancel": obj({"id": STRING}, ["id"]),
}
#: The issuing desk's tools (B-121), served only by the cloud instance and only to a desk key (scope `keys.issue`).
CLIENT_NAME = {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,63}$"}
DESK_SCHEMAS = {
 "client.issue": obj({"name": CLIENT_NAME, "scopes": {"type": "array", "minItems": 1, "maxItems": 3, "uniqueItems": True,
                                                      "items": {"enum": ["read", "research.run", "tools.call"]}},
                      "dailyUsd": {"type": "number", "minimum": 10, "maximum": 1000},
                      "class": {"enum": ["interactive", "automated"]}}, ["name"]),
 "client.rotate": obj({"name": CLIENT_NAME}, ["name"]),
 "client.revoke": obj({"name": CLIENT_NAME}, ["name"]),
 "client.list": obj(),
}
DESK_DESCRIPTIONS = {
 "client.issue": "Issue a client key within this desk's grants and ceiling; the key is in this answer once, put it straight into the holder's vault slot. class interactive (a person, or an agent a person calls in that moment) has no daily ceiling and takes no dailyUsd; class automated (a pipeline or a schedule, the default) keeps one.",
 "client.rotate": "Rotate a key this desk issued; the new key is in this answer once.",
 "client.revoke": "Revoke a key this desk issued, for good.",
 "client.list": "The keys this desk issued: names, classes, scopes, ceilings (null for an interactive key, never 0), prefixes and dates, never a key.",
}
#: The Costs section's two operations (B-155; rule R33 O16, pattern `costs-panel` 1.0.0, contract DEC-0183): the
#: dashboard's section and its edit control as capabilities (R33 O8). Behind the two doors, never listed there.
LIMIT_ID = {"enum": list(costs.cp.LIMIT_IDS)}
COSTS_SCHEMAS = {
 "costs.panel": obj(),
 "spend.limits.set": {**obj({"limitId": LIMIT_ID, "limitUsd": {"oneOf": [{"type": "number", "exclusiveMinimum": 0}, {"type": "null"}]},
                             "enforced": {"type": "boolean"}, "reason": {"type": "string", "minLength": 1, "maxLength": 500},
                             "idempotencyKey": STRING}, ["limitId", "reason", "idempotencyKey"]), "minProperties": 4},
}
#: An organization's report memory (B-160): read with any key holding `read`; an organization key lists its
#: organization's reports, any other key its own.
REPORTS_SCHEMAS = {
 "research.reports.list": obj({"runbook": STRING, "query": {"type": "string", "maxLength": 200},
                               "limit": {"type": "integer", "minimum": 1, "maximum": 100}}),
}
REPORTS_DESCRIPTIONS = {
 "research.reports.list": "List the finished research reports of the caller's organization (an organization key) or its own, newest first: id, runbook, inputs, who ran it, when. Read one with research.artifact.get.",
}
COSTS_DESCRIPTIONS = {
 "costs.panel": "Spend by UTC day, ISO week and month with chart series, the limits in force, the emergency stop and the last limit changes.",
 "spend.limits.set": "Change one spending limit: its limitUsd (null clears it), its enforced, or both. Lowering or a first amount is the caller's act; raising, clearing or turning off needs the operator's words in _meta.decision.",
}
CAPABILITIES = list(SCHEMAS)[:5]
for name in CAPABILITIES:
    SCHEMAS[name] = {"$id": BASE + name + ".input.json", **SCHEMAS[name]}
JOBS = {"research.run", "research.tools.call", "research.tutorial"}
# The envelope fields are Fabric's normative contract; the external pin validates
# their complete constraints. This self-contained union keeps clients usable offline.
RESULT_SCHEMA = {"type": "object", "required": ["id", "contractVersion", "outcome", "done", "proof", "scope", "notVerified", "artifacts", "createdAt", "producer", "output", "usage"],
                 "properties": {"output": {"type": "object"}}}
HANDLE_SCHEMA = obj({"job": obj({"id": dict(STRING, pattern="^[A-Za-z0-9._:-]+$"), "status": {"enum": ["working", "completed"]}}, ["id", "status"]),
                    # B-160: an organization's ready report answered instead of a new run (status completed)
                    "reused": obj({"id": STRING, "completedAt": {"type": "string"}, "by": {"type": ["string", "null"]}})}, ["job"])


OUTPUTS = {name: {"$id": BASE + name + ".output.json", **({"type": "object"} if name in JOBS else RESULT_SCHEMA)} for name in CAPABILITIES}

def tool_effect(name):
    """Each tool's declared effect class — the manifest's, and the delegation
    gate's ceiling check reads the same map."""
    return "charge" if name in {"research.run", "research.tools.call"} else "draft" if name in JOBS else "none"


EFFECTS = {name: tool_effect(name) for name in SCHEMAS} | {"costs.panel": "none", "spend.limits.set": "draft",
                                                            "research.reports.list": "none"}


def tools_list(desk=False):
    tools = []
    for name, schema in SCHEMAS.items():
        effect = tool_effect(name)
        out = {"type": "object", "oneOf": [{**RESULT_SCHEMA, "properties": {"output": OUTPUTS[name]}}, HANDLE_SCHEMA]} if name in JOBS else OUTPUTS[name] if name in CAPABILITIES else {"type": "object", "required": ["job"]}
        tools.append({"name": name, "description": {
            "research.run": "Run a research runbook; durable job that starts within the caller's daily allowance (an interactive client key has no ceiling and starts at once), above it waits for the operator.",
            "research.tools.call": "Call one Prowl data tool with its parameters; durable job, same allowance rule as research.run.",
            "research.tutorial": "Create a clearly labeled synthetic learning job; never contacts providers.",
            "research.list_runbooks": "List local runbooks, typed inputs and tool budgets.",
            "research.artifact.get": "Read a bounded artifact from this service's job; never arbitrary paths.",
            "fabric.job.get": "Read job progress/result. Decisions above the caller's allowance are the operator's, in the authenticated dashboard.",
            "fabric.job.cancel": "Cancel this job. Completed upstream charges are not reversed."}[name],
            "inputSchema": schema, "outputSchema": out,
            "annotations": {"readOnlyHint": effect == "none" and name != "fabric.job.cancel", "destructiveHint": effect not in {"none", "draft"},
                            "idempotentHint": True, "openWorldHint": effect == "charge"}})
    for name, schema in REPORTS_SCHEMAS.items():
        tools.append({"name": name, "description": REPORTS_DESCRIPTIONS[name], "inputSchema": schema,
                      "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True,
                                      "openWorldHint": False}})
    for name, schema in COSTS_SCHEMAS.items():
        tools.append({"name": name, "description": COSTS_DESCRIPTIONS[name], "inputSchema": schema,
                      "annotations": {"readOnlyHint": name == "costs.panel", "destructiveHint": False,
                                      "idempotentHint": True, "openWorldHint": False}})
    if desk:
        for name, schema in DESK_SCHEMAS.items():
            tools.append({"name": name, "description": DESK_DESCRIPTIONS[name], "inputSchema": schema,
                          "annotations": {"readOnlyHint": name == "client.list", "destructiveHint": name == "client.revoke",
                                          "idempotentHint": name == "client.list", "openWorldHint": False}})
    return tools


# --- the compact surface: two doors, search and execute (R33 O15, patterns/compact-mcp 1.2.0; B-154) -------------
SEARCH_TOOL, EXECUTE_TOOL = "research.search", "research.execute"
#: the date the operations' own tool names left tools/list; a call by one still answers, marked retired (R28)
RETIRED_SINCE = "2026-11-21"
#: `/mcp?surface=capabilities` keeps the full listing for a host or probe that reads every capability's schema
FULL_SURFACE = "capabilities"
#: the fabric-interop job tools stay listed beside the doors: the protocol requires them by name, so they take
#: seats of the three exceptions (the pattern's ruling). Measured on this service's gateway as well:
#: fabric.job.get, 289 of 374 calls, 2026-10-10 to 2026-11-16 (agents database rollout row RO-816).
JOB_TOOLS = ("fabric.job.get", "fabric.job.cancel")
#: one written line per operation, read against its handler (the contract's CM-3: at most 200 characters)
PURPOSES = {
 "research.run": "Run a research runbook as a durable job; starts within the caller's daily allowance, above it waits for the operator.",
 "research.tools.call": "Call one Prowl data tool with its parameters as a durable paid job, under the same allowance rule as research.run.",
 "research.tutorial": "Create a clearly labeled synthetic learning job; it never contacts a provider and costs nothing.",
 "research.list_runbooks": "List the runbooks with their typed inputs and tool budgets.",
 "research.artifact.get": "Read one artifact (report.md, ledger.json, checkpoint.json, result.json) of the caller's own job.",
 "research.reports.list": "List the finished reports of the caller's organization (or its own), newest first, to reuse one before ordering a new run.",
 "costs.panel": "Read the Costs section: spend by UTC day, ISO week and month with chart series, the limits, the emergency stop and the last changes.",
 "spend.limits.set": "Change one spending limit. Lowering or a first amount is the caller's act; raising, clearing or turning off needs the operator's words in _meta.decision.",
 "client.issue": "Issue a client key within this desk's grants and ceiling; the key is in the answer once. Desk keys only.",
 "client.rotate": "Rotate a key this desk issued; the new key is in the answer once. Desk keys only.",
 "client.revoke": "Revoke a key this desk issued, for good. Desk keys only.",
 "client.list": "List the keys this desk issued: names, classes, scopes, ceilings, prefixes and dates, never a key. Desk keys only.",
}
EXAMPLES = {
 "research.run": {"runbook": "market-pulse", "inputs": {"market": "AI SDR tools"}, "idempotencyKey": "market-pulse-2026-11-21"},
 "research.tools.call": {"tool": "google_news", "params": {"q": "ai agents"}, "idempotencyKey": "news-2026-11-21"},
 "research.tutorial": {"idempotencyKey": "tutorial-1"},
 "research.list_runbooks": {},
 "research.artifact.get": {"id": "pr-0123456789abcdef0123", "name": "report.md"},
 "research.reports.list": {"runbook": "market-pulse", "query": "ai sdr"},
 "costs.panel": {},
 "spend.limits.set": {"limitId": "costs.day", "limitUsd": 25, "reason": "A day's research fits 25 USD.", "idempotencyKey": "day-limit-2026-11-21"},
 "client.issue": {"name": "anna-laptop", "scopes": ["read", "research.run"], "class": "interactive"},
 "client.rotate": {"name": "anna-laptop"},
 "client.revoke": {"name": "anna-laptop"},
 "client.list": {},
}
#: the pattern's effect class per operation; the delegation gate keeps reading EFFECTS (charge, draft, none)
COMPACT_EFFECTS = {"research.run": "money", "research.tools.call": "money", "research.tutorial": "write",
                   "spend.limits.set": "write", "client.issue": "write", "client.rotate": "write", "client.revoke": "delete"}


def operation_idempotency(name):
    """The key the operation's own tool takes (CM-4): the three job capabilities require `idempotencyKey`,
    every other operation takes none, so a key sent to it through execute is ignored as by its own name."""
    return "required" if name in JOBS or name == "spend.limits.set" else "none"


def operation_names(desk=False):
    """Every operation behind the doors, in declared order: the capabilities, then the desk's when it is served."""
    return list(CAPABILITIES) + list(REPORTS_SCHEMAS) + list(COSTS_SCHEMAS) + (list(DESK_SCHEMAS) if desk else [])


def compact_surface(desk=False, usage=None):
    """The pattern's surface over this service's operations. It answers search; execute re-enters the service's
    own call path (`Protocol.handle`), so the gate, the schema, the idempotency and the job record are the
    operation's own."""
    full = {t["name"]: t for t in tools_list(desk)}
    ops = [compact_mcp.operation(
        name, PURPOSES[name], full[name]["inputSchema"], None, example=EXAMPLES[name],
        effect=COMPACT_EFFECTS.get(name, "read"), idempotency=operation_idempotency(name),
        gate="relayed" if name == "spend.limits.set" else "none",
        output_schema=full[name].get("outputSchema"), words=full[name]["description"])
        for name in operation_names(desk)]
    return compact_mcp.CompactSurface(ops, domain="research", job_tools=JOB_TOOLS, retired=RETIRED_SINCE, usage=usage)


def compact_tools(desk=False):
    """tools/list on the door agents register: research.search and research.execute, then the protocol's job tools."""
    full = {t["name"]: t for t in tools_list(desk)}
    search, execute = compact_surface(desk).tools()
    search = {**search, "outputSchema": compact_mcp.SEARCH_ANSWER_SCHEMA,
              "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}}
    execute = {**execute, "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False,
                                          "openWorldHint": True}}
    return [search, execute] + [full[name] for name in JOB_TOOLS]


def typed_refusal(code, message, data=None):
    """A compact-surface refusal as an MCP error result: `{error: {code, message, data}}`."""
    body = {"error": {"code": code, "message": message, "data": data or {}}}
    return {"content": [{"type": "text", "text": code}], "structuredContent": body, "isError": True}


def interop_error(error):
    """The job error in the shape the pinned interop schema accepts: code, message and
    data only. A job a build before B-075 stored carries terminalCode beside them."""
    if not isinstance(error, dict) or "terminalCode" not in error:
        return error
    rest = {k: v for k, v in error.items() if k != "terminalCode"}
    return {**rest, "data": {**rest.get("data", {}), "terminalCode": error["terminalCode"]}}


#: The registered Fabric service key (id.instance) Fabric Dashboards opens this service by: `<id>.default` on a
#: machine, `<id>.cloud` for a cloud instance (`scripts/cloud.py register` writes that descriptor; B-125: the cloud's
#: approval link named the local service, which is another service or none).
DASHBOARD_SERVICE = f"{SERVICE_ID}.default"
CLOUD_DASHBOARD_SERVICE = f"{SERVICE_ID}.cloud"


def dashboard_open_link(page: str, service: str = DASHBOARD_SERVICE) -> str:
    """The Fabric Dashboards link to a page of this dashboard (operator rule 2026-10-24: agent pages open only
    in Fabric Dashboards, never in a browser). No token or login code: the host authenticates."""
    return f"fabric-dashboards://service/{service}?path={quote(page, safe='')}"


def job_view(job, service: str = DASHBOARD_SERVICE):
    view = {k: job[k] for k in ["id", "status", "updatedAt"]}
    view["statusMessage"] = job["phase"]
    if job["status"] == "working":
        view["pollIntervalMs"] = 2000
    if job["status"] == "completed":
        view["result"] = job["result"]
    if job["status"] == "failed":
        view["error"] = interop_error(job["error"])
    if job["status"] == "input_required":
        # A URL elicitation prevents an untrusted caller from supplying its own
        # assertion that a human approved. Host login stays outside MCP credentials.
        view["inputRequests"] = {job["proposal"]["digest"]: {"method": "elicitation/create", "params": {"mode": "url", "message": "Operator authentication required. Open this request in Fabric Dashboards and approve or reject the exact proposal.",
                "url": dashboard_open_link("/dashboard#/requests/" + job["id"], service)}}}
    return {"job": view}


def artifact(store, job_id, name):
    job = store.job(job_id)
    if name not in {"report.md", "ledger.json", "checkpoint.json", "result.json"}:
        raise ValueError("Allowed artifacts: report.md, ledger.json, checkpoint.json, result.json")
    root = (store.root / "runs" / run_dir_name(job)).resolve()
    path = root / name
    if not path.is_file() or path.is_symlink() or path.resolve().parent != root:
        raise KeyError("artifact-not-found")
    if path.stat().st_size > 8_000_000:
        raise ValueError("Artifact exceeds 8 MB read limit; inspect the local data directory")
    return {"name": name, "content": path.read_text(), "classification": "project-internal"}


class Protocol:
    def __init__(self, runtime, desk=None, dashboard_service=DASHBOARD_SERVICE):
        self.runtime = runtime
        self.desk = desk  # the cloud instance's client store; None on the local service (no desk tools)
        self.dashboard_service = dashboard_service
        # calls per operation and UTC day (no call text, no caller): what a direct seat would be measured by
        root = getattr(getattr(runtime, "store", None), "root", None)
        self.usage = compact_mcp.UsageCounter(root / "mcp-usage.json") if root is not None else None

    async def handle(self, body, headers, authorize=None, surface=None):
        """`authorize(tool)` answers the delegation verdict for one tools/call
        (service.delegation.DelegationPolicy.check); a refusal is the call's
        result, never a transport error. `surface`: FULL_SURFACE lists every
        capability as its own tool; otherwise tools/list is the two doors."""
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
            return self.error(None, -32600, "Invalid Request"), 400
        rid, method, params = body.get("id"), body["method"], body.get("params", {})
        if not isinstance(params, dict) or not isinstance(params.get("_meta", {}), dict):
            return self.error(rid, -32602, "Invalid params"), 400
        meta = params.get("_meta", {})
        version = meta.get(META + "protocolVersion", headers.get("mcp-protocol-version", "2025-03-26"))
        if version not in SUPPORTED:
            return self.error(rid, -32022, "Unsupported protocol version", {"supported": SUPPORTED, "requested": version}), 400
        modern = version == VERSION
        if modern:
            matches = headers.get("mcp-protocol-version") == meta.get(META + "protocolVersion") and headers.get("mcp-method") == method
            if method == "tools/call":
                name = headers.get("mcp-name", "")
                if name.startswith("=?base64?") and name.endswith("?="):
                    try:
                        name = base64.b64decode(name[9:-2], validate=True).decode()
                    except Exception:
                        name = None
                matches = matches and name == params.get("name")
            if not matches:
                return self.error(rid, -32020, "HeaderMismatch"), 400
            if not isinstance(meta.get(META + "clientInfo"), dict) or not isinstance(meta.get(META + "clientCapabilities"), dict):
                return self.error(rid, -32602, "Required client metadata missing"), 400
        if rid is None:
            return None, 202
        try:
            trace = child_trace(meta.get("traceparent"))
            info = {"name": SERVICE_ID, "version": __version__, "title": SERVICE_NAME}
            if method == "initialize":
                result = {"protocolVersion": params.get("protocolVersion") if params.get("protocolVersion") in SUPPORTED else "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": info, "instructions": "Call research.search for the operations, then research.execute to run one (start with research.list_runbooks). Jobs require operator review. Never retry paid failures blindly. Degraded reasons are at the service well-known endpoint."}
            elif method == "server/discover":
                result = {"resultType": "complete", "_meta": {META + "serverInfo": info}, "supportedVersions": SUPPORTED, "capabilities": {"tools": {}}, "instructions": "research.search lists the operations, research.execute runs one. Use jobs and poll fabric.job.get; operator approval in Fabric Dashboards."}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                desk = self.desk is not None
                result = {"tools": tools_list(desk) if surface == FULL_SURFACE else compact_tools(desk)}
                if modern:
                    result["resultType"] = "complete"
            elif method == "tools/call":
                name, args = params.get("name"), params.get("arguments", {})
                desk = self.desk is not None
                settled = False  # a gate's refusal carries its own trace
                if name == SEARCH_TOOL:
                    operation, via = name, "search"
                    result = self.search(args, authorize, desk, trace)
                elif name == EXECUTE_TOOL:
                    via = "execute"
                    operation, result, stored_trace, settled = self.execute(args, meta, authorize, desk)
                    trace = stored_trace or trace
                elif name in SCHEMAS or name in COSTS_SCHEMAS or name in REPORTS_SCHEMAS or (desk and name in DESK_SCHEMAS):
                    # a job tool is listed; an operation's own name left the listing and still answers (R28)
                    operation, via = name, "direct" if name in JOB_TOOLS or surface == FULL_SURFACE else "name"
                    result, stored_trace, settled = self.run_tool(name, args, meta, authorize, desk)
                    trace = stored_trace or trace
                    if via == "name" and name not in COSTS_SCHEMAS and name not in REPORTS_SCHEMAS:  # never had a listed name
                        result.setdefault("_meta", {})["retired"] = {"since": RETIRED_SINCE, "replacedBy": EXECUTE_TOOL}
                else:
                    return self.error(rid, -32602, "Unknown tool"), 400
                self.audit(operation, via, result)
                if modern:
                    result["resultType"] = "complete"
                if settled:
                    return {"jsonrpc": "2.0", "id": rid, "result": result}, 200
            else:
                return self.error(rid, -32601, "Method not found"), 404
            if trace:
                result.setdefault("_meta", {})["traceparent"] = trace
            return {"jsonrpc": "2.0", "id": rid, "result": result}, 200
        except ValueError as exc:
            return self.error(rid, -32602, str(exc)), 400

    def run_tool(self, name, args, meta, authorize, desk):
        """One operation by its own name, the one path every route takes: the caller's gate for this operation,
        its input schema, then the call. Answers (result, the stored trace, whether a gate refused)."""
        schemas = SCHEMAS | COSTS_SCHEMAS | REPORTS_SCHEMAS | (DESK_SCHEMAS if desk else {})
        trace = child_trace(meta.get("traceparent"))
        verdict = authorize(name) if authorize is not None else {"ok": True}
        if not verdict.get("ok"):
            return refusal_tool_result(verdict, child_trace(meta.get("traceparent"))), None, True
        stored_trace = None
        try:
            Draft202012Validator(schemas[name]).validate(args)
            data, stored_trace = self.call(name, args, meta.get("traceparent"), recorded(verdict), meta.get("decision"))
            result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}], "structuredContent": data, "isError": False}
        except Refused as exc:
            result = refusal_tool_result(exc.verdict, trace)
        except costs.cp.Refused as exc:  # spend.limits.set: the contract's typed refusals (DEC-0183 SL-2)
            result = typed_refusal(exc.code, exc.message)
        except (ValueError, KeyError, Conflict) as exc:
            code = exc.args[0] if isinstance(exc, KeyError) else "request-rejected"
            result = {"content": [{"type": "text", "text": str(code)}], "structuredContent": {"error": {"code": str(code), "message": str(exc)[:300]}}, "isError": True}
        except Exception as exc:
            result = {"content": [{"type": "text", "text": "Request validation failed: " + type(exc).__name__}], "isError": True}
        return result, stored_trace, False

    def search(self, args, authorize, desk, trace):
        """research.search: the catalogue, the contract's closed `compact-mcp-search/1`; each operation's effect
        and the key execute applies travel beside it in `_meta.hints`. Any authenticated caller may read it: it
        names operations and opens none of them."""
        verdict = authorize(SEARCH_TOOL) if authorize is not None else {"ok": True}
        if not verdict.get("ok"):
            return refusal_tool_result(verdict, trace)
        problems = compact_mcp.validate(args, compact_mcp.SEARCH_INPUT_SCHEMA) if isinstance(args, dict) else ["arguments is not an object"]
        if problems:
            return typed_refusal("invalid-arguments", "; ".join(problems))
        surface = compact_surface(desk, self.usage)
        answer = surface.search(args.get("query"), args.get("limit", compact_mcp.SEARCH_LIMIT),
                                names=args.get("names"), cursor=args.get("cursor"))
        return {"content": [{"type": "text", "text": json.dumps(answer, ensure_ascii=False)}], "structuredContent": answer,
                "isError": False, "_meta": {"hints": surface.hints(answer)}}

    def execute(self, args, meta, authorize, desk):
        """research.execute: `{operation, arguments?, idempotencyKey?}`. It checks its own arguments, then takes
        the operation's own path (`run_tool`), so execute never opens what the operation's own tool refuses.
        Answers (operation, result, the stored trace, whether a gate refused)."""
        problems = compact_mcp.validate(args, compact_mcp.EXECUTE_INPUT_SCHEMA) if isinstance(args, dict) else ["arguments is not an object"]
        if problems:
            return None, typed_refusal("invalid-arguments", "; ".join(problems)), None, False
        name, known = args["operation"], operation_names(desk)
        if name not in known:
            return name, typed_refusal("unknown-operation", f"No operation {name}; {SEARCH_TOOL} lists them.",
                                       {"near": difflib.get_close_matches(name, known, 3, 0.5)}), None, False
        inner, key = dict(args.get("arguments") or {}), args.get("idempotencyKey")
        if operation_idempotency(name) == "required":
            own = inner.get("idempotencyKey")
            if own is None and key is None:
                return name, typed_refusal("idempotency-required", f"{name} takes an idempotencyKey."), None, False
            if own is not None and key is not None and own != key:
                return name, typed_refusal("invalid-arguments", "idempotencyKey and arguments.idempotencyKey differ; send one."), None, False
            inner["idempotencyKey"] = own if own is not None else key
        result, stored_trace, settled = self.run_tool(name, inner, meta, authorize, desk)
        return name, result, stored_trace, settled

    def audit(self, operation, via, result):
        """One record per call: the operation, the route it came by (`search`, `execute`, `direct` for a listed
        job tool, `name` for an operation's own retired tool name) and the outcome; an answered call is counted."""
        failed = bool(result.get("isError"))
        error = (result.get("structuredContent") or {}).get("error") if failed else None
        outcome = (error.get("code") if isinstance(error, dict) else "error") if failed else "ok"
        emit(log, "mcp.call", operation=operation, via=via, outcome=outcome)
        if self.usage is not None and operation and not failed and via != "search":
            try:
                self.usage.count(operation)
            except OSError:  # a full disk loses a count, never the answer
                pass

    @staticmethod
    def error(rid, code, message, data=None):
        err = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {"jsonrpc": "2.0", "id": rid, "error": err}

    def call(self, name, args, trace, delegation=None, decision=None):
        rt = self.runtime
        if name == "costs.panel":
            if str((delegation or {}).get("principal") or "").startswith("org:"):  # B-162: its own organization only
                return costs.org_panel(rt.store, delegation), child_trace(trace)
            return costs.panel(rt.store), child_trace(trace)
        if name == "spend.limits.set":
            # who asked is kept as an opaque reference; the operator's words, when relayed, travel in _meta.decision
            who = (delegation or {}).get("principal") or "agent"
            return costs.set_limit(rt.store, args, via="agent", decision=decision, by_ref=who), child_trace(trace)
        if name in DESK_SCHEMAS:
            return self.desk_call(name, args, delegation), child_trace(trace)
        if name == "research.reports.list":
            return reports.listing(rt.store, delegation, args.get("runbook"), args.get("query"),
                                   args.get("limit") or reports.LIST_LIMIT), child_trace(trace)
        if name in JOBS:
            req = {k: v for k,v in args.items() if k != "idempotencyKey"}
            req["kind"] = {"research.run": "research", "research.tools.call": "tool", "research.tutorial": "tutorial"}[name]
            job = rt.create(req, args["idempotencyKey"], trace, delegation=delegation)
            if job.get("reused"):
                summary = reports.summary(job)
                return ({"job": {"id": job["id"], "status": "completed"},
                         "reused": {"id": job["id"], "completedAt": summary["completedAt"], "by": summary["by"]}},
                        job.get("traceparent"))
            return {"job": {"id": job["id"], "status": "working"}}, job.get("traceparent")
        if name.startswith("fabric.job."):
            if args.get("inputResponses"):
                raise ValueError("Decisions require the operator session in Fabric Dashboards; MCP caller credentials cannot approve their own jobs")
            # A delegated caller reads and cancels only the jobs it started for its
            # principal (the kit's rule for job tools); refused with the DL-19 code.
            require_owner(rt.store.job(args["id"]), delegation)
            job = rt.cancel(args["id"]) if name.endswith("cancel") else rt.store.job(args["id"])
            return job_view(job, self.dashboard_service), job.get("traceparent")
        if name == "research.list_runbooks":
            output = {"runbooks": runbooks()}
        else:
            require_owner(rt.store.job(args["id"]), delegation)
            output = artifact(rt.store, args["id"], args["name"])
        fake_job = {"id": "read-" + __import__('secrets').token_hex(8), "request": {}, "traceparent": child_trace(trace)}
        return rt.envelope(fake_job, output, 0), fake_job["traceparent"]

    def desk_call(self, name, args, delegation):
        """The issuing desk (B-121): the caller's own client name is the desk; the store refuses anything but a live
        desk key and anything outside the desk's grants, ceiling and own issued keys."""
        principal = (delegation or {}).get("principal") or ""
        if (delegation or {}).get("tier") != "client" or not principal.startswith("client:"):
            raise Refused("scope-not-granted", "desk-key-required")
        desk = principal[len("client:"):]
        if name == "client.list":
            return {"clients": self.desk.desk_list(desk)}
        if name == "client.revoke":
            self.desk.desk_revoke(desk, args["name"])
            return {"name": args["name"], "revoked": True}
        key = (self.desk.desk_issue(desk, args["name"], args.get("scopes"), args.get("dailyUsd"), args.get("class"))
               if name == "client.issue"
               else self.desk.desk_rotate(desk, args["name"]))
        record = next(c for c in self.desk.desk_list(desk) if c["name"] == args["name"])
        return {"name": args["name"], "key": key, "scopes": record["scopes"], "dailyUsd": record["dailyUsd"], "class": record["keyClass"],
                "prefix": record["prefix"], "shownOnce": True}
