"""Loopback HTTP service, host authentication and operator dashboard API."""
from __future__ import annotations
import hashlib
import json
import os
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit
from datetime import datetime, timedelta, timezone
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.middleware.base import BaseHTTPMiddleware
from .delegation import DelegationPolicy, is_loopback, refusal_http
from .identity import HEADER, SERVICE_ID, SERVICE_NAME
from .protocol import EFFECTS, Protocol, CAPABILITIES, artifact
from .runtime import Runtime, runbooks
from .store import Store, Conflict, now
from .runtime import run_dir_name
from research_agent import __version__
from research_agent.agent import tool_limits
from research_agent.evidence.store import COMPLETED, ArtifactStore

STATIC = Path(__file__).parent / "static"


def code_digest():
    value = hashlib.sha256()
    for path in sorted(Path(__file__).parents[1].rglob("*")):
        if path.is_file() and path.suffix in {".py", ".js", ".css", ".html", ".md"}:
            value.update(str(path.relative_to(Path(__file__).parents[1])).encode())
            value.update(path.read_bytes())
    return "sha256:" + value.hexdigest()


#: The dashboard's declaration (ED-9, DEC-0036): the kit it ships and the
#: estate themes the host may apply.
DASHBOARD_EXTENSION = "https://fabric.passioncode.ai/agent-contract/extensions/dashboard/0.1"
DASHBOARD_KIT = "fabric-dashboard-kit@1.1.5"
DASHBOARD_THEMES = ("graphite", "fabric", "paper", "forest", "ocean", "ember", "contrast")



#: Which client-key scope each capability needs in the cloud (B-099 M3). The
#: fabric.job.* tools act on the caller's own jobs only (require_owner).
SCOPE_OF = {"research.list_runbooks": "read", "research.artifact.get": "read", "research.tutorial": "read",
            "research.run": "research.run", "research.tools.call": "tools.call"}


@dataclass(frozen=True)
class CloudSettings:
    """The cloud instance (B-099): its public https origin and its client keys.
    Absent, `create_app` is the loopback service unchanged (REQ-1)."""
    origin: str
    clients: object

    @property
    def host(self) -> str:
        return urlsplit(self.origin).netloc


def display(store, job):
    """What the dashboard shows that the stored job does not carry in its language:
    the coverage of every limited tool the job used, derived now so a job stored
    before B-078 shows it too (a tool job: its completed calls; research: its
    completed steps). It follows today's limits table, not the one of the call."""
    if job is None:
        return {"coverage": []}
    request = job.get("request") or {}
    tools = []
    if request.get("kind") == "tool":
        # Only a call that ran: a pending, rejected or refused job sent nothing.
        tools = [c["name"] for c in store.calls(job["id"]) if c["kind"] == "tool" and c["status"] == "completed"]
    elif request.get("kind") == "research":
        try:
            checkpoint = ArtifactStore(store.root / "runs" / run_dir_name(job)).load_checkpoint()
        except (ValueError, OSError):
            checkpoint = None
        tools = [s.tool for s in checkpoint.steps if s.state == COMPLETED] if checkpoint else []
    return {"coverage": tool_limits.statements_ru(tools)}

def page() -> str:
    """The dashboard page, named after this service (identical bytes for the original)."""
    html = (STATIC / "index.html").read_text()
    return (html.replace("<title>Prowl Research · Fabric</title>", f"<title>{SERVICE_NAME} · Fabric</title>")
                .replace('<p class="fd-title">PROWL · Research</p>', f'<p class="fd-title">{HEADER}</p>')
                .replace("<footer>Prowl Research <span>", f"<footer>{SERVICE_NAME} <span>"))


def create_app(root: Path, host_token: str, agent_token: str | None, port=18764, build=None, delegation=None,
               cloud: CloudSettings | None = None):
    delegation = delegation if delegation is not None else DelegationPolicy.from_env(EFFECTS)
    store = Store(root)
    store.recover()
    rt = Runtime(store)
    rt.origin = cloud.origin if cloud else f"http://127.0.0.1:{port}"
    proto = Protocol(rt)
    started = now()
    build = build or {"digest": code_digest()}
    # The cloud cookie is bound to its https host: no Domain, Path=/, Secure (B-099 REQ-6).
    cookie = "__Host-prowl_operator" if cloud else "prowl_operator_" + str(port)
    instance = "cloud" if cloud else "default"

    @asynccontextmanager
    async def lifespan(app):
        with store.db:
            store.event("service.started", f"{SERVICE_NAME} запущен.")
        yield
        with store.db:
            store.event("service.stopping", f"{SERVICE_NAME} завершает работу.")
        await rt.close()
        store.db.close()

    def degraded():
        result = []
        if not os.environ.get("PROWL_API_KEY"):
            result.append({"source": "prowl", "reason": "Ключ Prowl не подключён. Доступны локальные данные и обучение."})
        if not (os.environ.get("RESEARCH_LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY")):
            result.append({"source": "llm", "reason": "Ключ модели не подключён. Исследования недоступны."})
        return result

    def health():
        reasons = degraded()
        return {"protocol": "fabric-service/0.1", "service": {"id": SERVICE_ID, "instance": instance, "name": SERVICE_NAME, "version": __version__, "build": build},
                "process": {"pid": os.getpid(), "startedAt": started}, "status": "stopping" if rt.stopping else "degraded" if reasons else "ready", "degraded": reasons,
                "surfaces": {"dashboard": {"path": "/dashboard", "login": True}, "mcp": {"path": "/mcp", "transport": "streamable-http", "auth": "own", "capabilities": CAPABILITIES},
                             "events": {"path": "/fabric/v1/events"}, "usage": {"path": "/fabric/v1/usage"}}, "update": {"available": None},
                "extensions": {DASHBOARD_EXTENSION: {"minWidth": 360, "appearance": ["scheme", "theme"],
                                                     "themes": list(DASHBOARD_THEMES), "kit": DASHBOARD_KIT}},
                **({"auth": {"delegation": delegation.declaration()}} if delegation.declaration() else {})}

    def token_matches(request, token):
        return token is not None and secrets.compare_digest(request.headers.get("authorization", ""), "Bearer " + token)

    def client_of(request):
        value = request.headers.get("authorization", "")
        return cloud.clients.verify(value[7:]) if value.startswith("Bearer ") else None

    def client_verdict(client, tool):
        needed = SCOPE_OF.get(tool)
        if needed is not None and needed not in client["scopes"]:
            return {"ok": False, "code": "scope-not-granted", "detail": "client-key-scope"}
        who = "client:" + client["name"]
        return {"ok": True, "tier": "client", "principal": who, "caller": who, "chain": [], "claims": None, "kid": None}

    def operator(request):
        return store.auth_valid("session", request.cookies.get(cookie, ""))

    async def body(request):
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 128000:
                raise ValueError("Request exceeds 128 KB")
            chunks.append(chunk)
        value = json.loads(b"".join(chunks))
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
        return value

    def delegation_refusal(code, detail):
        return {"ok": False, "code": code, "detail": detail}

    def refused(verdict):
        status, headers, payload = refusal_http(verdict)
        return Response(payload, status, headers=headers)

    async def endpoint(request: Request):
        path = request.url.path
        if path == "/.well-known/fabric-service":
            # Online, the description is the service token's (remote placement): no body without it.
            if cloud and not token_matches(request, host_token):
                return Response(status_code=401)
            return JSONResponse(health())
        if path == "/fabric/v1/login-code":
            if not token_matches(request, host_token):
                return JSONResponse({"error": "host token required"}, 401)
            code = store.auth_create("code", 90)
            expires = (datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat().replace("+00:00", "Z")
            return JSONResponse({"url": "/fabric/v1/login?code=" + code, "expiresAt": expires})
        if path == "/fabric/v1/login":
            if not store.auth_valid("code", request.query_params.get("code", ""), consume=True):
                return HTMLResponse(f"<p>Ссылка истекла или уже использована. Откройте {SERVICE_NAME} в Fabric Dashboards заново.</p>", 403)
            response = RedirectResponse("/dashboard", 302)
            response.set_cookie(cookie, store.auth_create("session", 28800), max_age=28800, httponly=True, samesite="Strict", path="/",
                                secure=bool(cloud))
            return response
        if path in {"/fabric/v1/events", "/fabric/v1/usage"}:
            if not token_matches(request, host_token):
                return JSONResponse({"error": "host token required"}, 401)
            if path.endswith("usage"):
                return JSONResponse(store.usage())
            limit = int(request.query_params.get("limit", "50"))
            if not 1 <= limit <= 200:
                raise ValueError("limit must be between 1 and 200")
            after = request.query_params.get("after")
            return JSONResponse(store.events(int(after) if after is not None else None, limit))
        if path == "/mcp" and cloud:
            # Online only a client key reaches the tools; the service token never does (DEC-0024, B-099 R-8).
            client = client_of(request)
            if client is None:
                return refused(delegation_refusal("unauthenticated", "no-client-key"))
            message = await body(request)
            data, status = await proto.handle(message, request.headers, authorize=lambda tool: client_verdict(client, tool))
            return JSONResponse(data, status) if data is not None else Response(status_code=status)
        if path == "/mcp":
            own = token_matches(request, agent_token)
            if not own and not DelegationPolicy.carries_token(request.headers):
                return refused(delegation_refusal("unauthenticated", "no-token"))
            loopback = is_loopback(request.client.host if request.client else None)
            message = await body(request)
            # A tools/call is judged per capability by the gate; any other method
            # (initialize, tools/list, ping) still needs an authentic, current token.
            if not own and message.get("method") != "tools/call" and not delegation.authenticate(request.headers):
                code = "unauthenticated" if delegation.configured else "issuer-unavailable"
                return refused(delegation_refusal(code, "token-not-verified" if delegation.configured else "no-trusted-issuer"))

            def authorize(tool):
                return delegation.check(tool, request.headers, own_token=own, loopback=loopback)

            data, status = await proto.handle(message, request.headers, authorize=authorize)
            return JSONResponse(data, status) if data is not None else Response(status_code=status)
        if path.startswith("/static/"):
            name = path.removeprefix("/static/")
            if name not in {"app.js", "styles.css", "fabric-dashboard.css", "fabric-dashboard.js",
                            "fabric-button.js", "Fraunces.ttf", "Newsreader.ttf", "JetBrainsMono.ttf"}:
                return Response(status_code=404)
            return FileResponse(STATIC / name)
        if not operator(request):
            if path in {"/", "/dashboard"}:
                return HTMLResponse('<!doctype html><html lang="ru"><meta charset="utf-8"><title>' + SERVICE_NAME + ' · вход</title><link rel="stylesheet" href="/static/styles.css"><main class="login"><p class="eyebrow">PROWL / RESEARCH</p><h1>Откройте через Fabric</h1><p>Сессия панели создаётся в Fabric Dashboards. Ключи не нужно вставлять в браузер.</p></main></html>', 401)
            return JSONResponse({"error": "Сессия истекла. Откройте сервис в Fabric Dashboards заново."}, 401)
        if request.method == "POST" and request.headers.get("x-prowl-request") != "1":
            return JSONResponse({"error": "request header required"}, 403)
        if path in {"/", "/dashboard"}:
            return HTMLResponse(page())
        if path == "/api/state":
            jobs = store.jobs()
            summaries = []
            for job in jobs:
                calls = store.calls(job["id"])
                costs = [c["costUsd"] for c in calls if c["costUsd"] is not None]
                summaries.append({k: job[k] for k in ["id", "status", "phase", "createdAt", "updatedAt", "request"]} | {
                    "delegation": job.get("delegation"), "via": job.get("via"), "runDir": job.get("runDir"),
                    "chainOwner": job.get("chainOwner"), "errorCode": (job.get("error") or {}).get("code"),
                    "costUsd": sum(costs) if costs else None, "unpricedCalls": sum(c["costUsd"] is None for c in calls), "calls": len(calls)})
            return JSONResponse({"at": now(), "health": health(), "jobs": summaries, "config": store.config(), "usage": store.usage(), "runbooks": runbooks()})
        if path == "/api/jobs" and request.method == "POST":
            data = await body(request)
            return JSONResponse(rt.create(data["request"], data["idempotencyKey"], via="dashboard"), 201)
        if path.startswith("/api/jobs/"):
            job_id = request.path_params["job_id"]
            if request.method == "GET":
                job = store.job(job_id)
                return JSONResponse({"job": job, "calls": store.calls(job_id), "display": display(store, job)})
            data = await body(request)
            if data.get("action") == "cancel":
                return JSONResponse(rt.cancel(job_id))
            if data.get("action") in {"approve", "reject"}:
                return JSONResponse(rt.decide(job_id, data.get("digest"), data["action"] == "approve"))
            raise ValueError("Unknown job action")
        if path == "/api/config" and request.method == "POST":
            data = await body(request)
            return JSONResponse(store.configure(data["revision"], data["values"]))
        if path == "/api/artifact":
            return JSONResponse(artifact(store, request.query_params["id"], request.query_params["name"]))
        return Response(status_code=404)

    routes = [Route(p, endpoint, methods=m) for p,m in [
        ("/.well-known/fabric-service", ["GET"]), ("/fabric/v1/login-code", ["POST"]), ("/fabric/v1/login", ["GET"]),
        ("/fabric/v1/events", ["GET"]), ("/fabric/v1/usage", ["GET"]), ("/mcp", ["POST"]),
        ("/static/{name}", ["GET"]), ("/", ["GET"]), ("/dashboard", ["GET"]), ("/api/state", ["GET"]),
        ("/api/jobs", ["POST"]), ("/api/jobs/{job_id}", ["GET", "POST"]), ("/api/config", ["POST"]), ("/api/artifact", ["GET"])]]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.runtime, app.state.store = rt, store

    async def guard(request, call_next):
        host = request.headers.get("host", "")
        if cloud:
            # Heroku's router ends TLS: the request is ours only for our host, forwarded as https.
            allowed_hosts, allowed_origins = {cloud.host}, {cloud.origin}
            wrong_scheme = request.headers.get("x-forwarded-proto") != "https"
        else:
            allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
            allowed_origins = {"http://" + h for h in allowed_hosts}
            wrong_scheme = False
        if wrong_scheme or host not in allowed_hosts or (request.headers.get("origin") is not None and request.headers["origin"] not in allowed_origins) or request.headers.get("sec-fetch-site") == "cross-site":
            response = JSONResponse({"error": "own origin required" if cloud else "local origin required"}, 403)
        else:
            try:
                response = await call_next(request)
            except Conflict as exc:
                response = JSONResponse({"error": str(exc)}, 409)
            except (ValueError, KeyError) as exc:
                response = JSONResponse({"error": str(exc)[:300]}, 400)
            except Exception:
                response = JSONResponse({"error": "Внутренняя ошибка. Обновите панель; повтор платного запроса не выполняется автоматически."}, 500)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response
    app.add_middleware(BaseHTTPMiddleware, dispatch=guard)
    return app
