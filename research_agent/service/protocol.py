"""Small dual-era JSON MCP surface, implemented from the public wire contract."""
from __future__ import annotations
import base64
import json
from urllib.parse import quote
from jsonschema import Draft202012Validator
from .delegation import Refused, recorded, refusal_tool_result, require_owner
from .runtime import child_trace, run_dir_name, runbooks
from .store import Conflict
from research_agent import __version__
from .identity import SERVICE_ID, SERVICE_NAME

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
                                                      "saved evidence is reused, nothing already paid is dispatched again."}),
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
CAPABILITIES = list(SCHEMAS)[:5]
for name in CAPABILITIES:
    SCHEMAS[name] = {"$id": BASE + name + ".input.json", **SCHEMAS[name]}
JOBS = {"research.run", "research.tools.call", "research.tutorial"}
# The envelope fields are Fabric's normative contract; the external pin validates
# their complete constraints. This self-contained union keeps clients usable offline.
RESULT_SCHEMA = {"type": "object", "required": ["id", "contractVersion", "outcome", "done", "proof", "scope", "notVerified", "artifacts", "createdAt", "producer", "output", "usage"],
                 "properties": {"output": {"type": "object"}}}
HANDLE_SCHEMA = obj({"job": obj({"id": dict(STRING, pattern="^[A-Za-z0-9._:-]+$"), "status": {"const": "working"}}, ["id", "status"])}, ["job"])


OUTPUTS = {name: {"$id": BASE + name + ".output.json", **({"type": "object"} if name in JOBS else RESULT_SCHEMA)} for name in CAPABILITIES}

def tool_effect(name):
    """Each tool's declared effect class — the manifest's, and the delegation
    gate's ceiling check reads the same map."""
    return "charge" if name in {"research.run", "research.tools.call"} else "draft" if name in JOBS else "none"


EFFECTS = {name: tool_effect(name) for name in SCHEMAS}


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
    if desk:
        for name, schema in DESK_SCHEMAS.items():
            tools.append({"name": name, "description": DESK_DESCRIPTIONS[name], "inputSchema": schema,
                          "annotations": {"readOnlyHint": name == "client.list", "destructiveHint": name == "client.revoke",
                                          "idempotentHint": name == "client.list", "openWorldHint": False}})
    return tools


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

    async def handle(self, body, headers, authorize=None):
        """`authorize(tool)` answers the delegation verdict for one tools/call
        (service.delegation.DelegationPolicy.check); a refusal is the call's
        result, never a transport error."""
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
                result = {"protocolVersion": params.get("protocolVersion") if params.get("protocolVersion") in SUPPORTED else "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": info, "instructions": "Start with research.list_runbooks. Jobs require operator review. Never retry paid failures blindly. Degraded reasons are at the service well-known endpoint."}
            elif method == "server/discover":
                result = {"resultType": "complete", "_meta": {META + "serverInfo": info}, "supportedVersions": SUPPORTED, "capabilities": {"tools": {}}, "instructions": "Use jobs and poll fabric.job.get; operator approval in Fabric Dashboards."}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": tools_list(desk=self.desk is not None)}
                if modern:
                    result["resultType"] = "complete"
            elif method == "tools/call":
                name, args = params.get("name"), params.get("arguments", {})
                schemas = SCHEMAS | (DESK_SCHEMAS if self.desk is not None else {})
                if name not in schemas:
                    return self.error(rid, -32602, "Unknown tool"), 400
                verdict = authorize(name) if authorize is not None else {"ok": True}
                if not verdict.get("ok"):
                    result = refusal_tool_result(verdict, child_trace(meta.get("traceparent")))
                    if modern:
                        result["resultType"] = "complete"
                    return {"jsonrpc": "2.0", "id": rid, "result": result}, 200
                try:
                    Draft202012Validator(schemas[name]).validate(args)
                    data, stored_trace = self.call(name, args, meta.get("traceparent"), recorded(verdict))
                    trace = stored_trace or trace
                    result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}], "structuredContent": data, "isError": False}
                except Refused as exc:
                    result = refusal_tool_result(exc.verdict, trace)
                except (ValueError, KeyError, Conflict) as exc:
                    code = exc.args[0] if isinstance(exc, KeyError) else "request-rejected"
                    result = {"content": [{"type": "text", "text": str(code)}], "structuredContent": {"error": {"code": str(code), "message": str(exc)[:300]}}, "isError": True}
                except Exception as exc:
                    result = {"content": [{"type": "text", "text": "Request validation failed: " + type(exc).__name__}], "isError": True}
                if modern:
                    result["resultType"] = "complete"
            else:
                return self.error(rid, -32601, "Method not found"), 404
            if trace:
                result.setdefault("_meta", {})["traceparent"] = trace
            return {"jsonrpc": "2.0", "id": rid, "result": result}, 200
        except ValueError as exc:
            return self.error(rid, -32602, str(exc)), 400

    @staticmethod
    def error(rid, code, message, data=None):
        err = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {"jsonrpc": "2.0", "id": rid, "error": err}

    def call(self, name, args, trace, delegation=None):
        rt = self.runtime
        if name in DESK_SCHEMAS:
            return self.desk_call(name, args, delegation), child_trace(trace)
        if name in JOBS:
            req = {k: v for k,v in args.items() if k != "idempotencyKey"}
            req["kind"] = {"research.run": "research", "research.tools.call": "tool", "research.tutorial": "tutorial"}[name]
            job = rt.create(req, args["idempotencyKey"], trace, delegation=delegation)
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
