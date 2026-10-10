"""Small dual-era JSON MCP surface, implemented from the public wire contract."""
from __future__ import annotations
import base64
import json
from pathlib import Path
from jsonschema import Draft202012Validator
from .runtime import child_trace, runbooks
from .store import Conflict

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
 "research.run": obj(dict(COMMON, runbook=STRING, inputs={"type": "object"}), ["idempotencyKey", "runbook", "inputs"]),
 "research.tools.call": obj(dict(COMMON, tool=STRING, params={"type": "object"}), ["idempotencyKey", "tool", "params"]),
 "research.tutorial": obj(COMMON, ["idempotencyKey"]),
 "research.list_runbooks": obj(),
 "research.artifact.get": obj({"id": STRING, "name": STRING}, ["id", "name"]),
 "fabric.job.get": obj({"id": STRING, "inputResponses": {"type": "object"}}, ["id"]),
 "fabric.job.cancel": obj({"id": STRING}, ["id"]),
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

def tools_list():
    tools = []
    for name, schema in SCHEMAS.items():
        effect = "charge" if name in {"research.run", "research.tools.call"} else "draft" if name in JOBS else "none"
        out = {"type": "object", "oneOf": [{**RESULT_SCHEMA, "properties": {"output": OUTPUTS[name]}}, HANDLE_SCHEMA]} if name in JOBS else OUTPUTS[name] if name in CAPABILITIES else {"type": "object", "required": ["job"]}
        tools.append({"name": name, "description": {
            "research.run": "Run a research runbook; durable job, operator approval required before paid work.",
            "research.tools.call": "Call one Prowl data tool with its parameters; durable approval job.",
            "research.tutorial": "Create a clearly labeled synthetic learning job; never contacts providers.",
            "research.list_runbooks": "List local runbooks, typed inputs and tool budgets.",
            "research.artifact.get": "Read a bounded artifact from this service's job; never arbitrary paths.",
            "fabric.job.get": "Read job progress/result. Operator decisions are made in the authenticated dashboard.",
            "fabric.job.cancel": "Cancel this job. Completed upstream charges are not reversed."}[name],
            "inputSchema": schema, "outputSchema": out,
            "annotations": {"readOnlyHint": effect == "none" and name != "fabric.job.cancel", "destructiveHint": effect not in {"none", "draft"},
                            "idempotentHint": True, "openWorldHint": effect == "charge"}})
    return tools


def job_view(job, origin="http://127.0.0.1:18764"):
    view = {k: job[k] for k in ["id", "status", "updatedAt"]}
    view["statusMessage"] = job["phase"]
    if job["status"] == "working":
        view["pollIntervalMs"] = 2000
    if job["status"] == "completed":
        view["result"] = job["result"]
    if job["status"] == "failed":
        view["error"] = job["error"]
    if job["status"] == "input_required":
        # A URL elicitation prevents an untrusted caller from supplying its own
        # assertion that a human approved. Host login stays outside MCP credentials.
        view["inputRequests"] = {job["proposal"]["digest"]: {"method": "elicitation/create", "params": {"mode": "url", "message": "Operator authentication required. Open this request in Fabric Dashboards and approve or reject the exact proposal.",
                "url": origin + "/dashboard#/requests/" + job["id"]}}}
    return {"job": view}


def artifact(store, job_id, name):
    store.job(job_id)
    if name not in {"report.md", "ledger.json", "checkpoint.json", "result.json"}:
        raise ValueError("Allowed artifacts: report.md, ledger.json, checkpoint.json, result.json")
    root = (store.root / "runs" / job_id).resolve()
    path = root / name
    if not path.is_file() or path.is_symlink() or path.resolve().parent != root:
        raise KeyError("artifact-not-found")
    if path.stat().st_size > 8_000_000:
        raise ValueError("Artifact exceeds 8 MB read limit; inspect the local data directory")
    return {"name": name, "content": path.read_text(), "classification": "project-internal"}


class Protocol:
    def __init__(self, runtime):
        self.runtime = runtime

    async def handle(self, body, headers):
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
            info = {"name": "prowl-research", "version": "0.2.0", "title": "Prowl Research"}
            if method == "initialize":
                result = {"protocolVersion": params.get("protocolVersion") if params.get("protocolVersion") in SUPPORTED else "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": info, "instructions": "Start with research.list_runbooks. Jobs require operator review. Never retry paid failures blindly. Degraded reasons are at the service well-known endpoint."}
            elif method == "server/discover":
                result = {"resultType": "complete", "_meta": {META + "serverInfo": info}, "supportedVersions": SUPPORTED, "capabilities": {"tools": {}}, "instructions": "Use jobs and poll fabric.job.get; operator approval in Fabric Dashboards."}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": tools_list()}
                if modern:
                    result["resultType"] = "complete"
            elif method == "tools/call":
                name, args = params.get("name"), params.get("arguments", {})
                if name not in SCHEMAS:
                    return self.error(rid, -32602, "Unknown tool"), 400
                try:
                    Draft202012Validator(SCHEMAS[name]).validate(args)
                    data, stored_trace = self.call(name, args, meta.get("traceparent"))
                    trace = stored_trace or trace
                    result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}], "structuredContent": data, "isError": False}
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

    def call(self, name, args, trace):
        rt = self.runtime
        if name in JOBS:
            req = {k: v for k,v in args.items() if k != "idempotencyKey"}
            req["kind"] = {"research.run": "research", "research.tools.call": "tool", "research.tutorial": "tutorial"}[name]
            job = rt.create(req, args["idempotencyKey"], trace)
            return {"job": {"id": job["id"], "status": "working"}}, job.get("traceparent")
        if name.startswith("fabric.job."):
            if args.get("inputResponses"):
                raise ValueError("Decisions require the operator session in Fabric Dashboards; MCP caller credentials cannot approve their own jobs")
            job = rt.cancel(args["id"]) if name.endswith("cancel") else rt.store.job(args["id"])
            return job_view(job, getattr(rt, "origin", "http://127.0.0.1:18764")), job.get("traceparent")
        if name == "research.list_runbooks":
            output = {"runbooks": runbooks()}
        else:
            output = artifact(rt.store, args["id"], args["name"])
        fake_job = {"id": "read-" + __import__('secrets').token_hex(8), "request": {}, "traceparent": child_trace(trace)}
        return rt.envelope(fake_job, output, 0), fake_job["traceparent"]
