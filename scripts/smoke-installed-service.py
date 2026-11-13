import asyncio
import json
import time
from pathlib import Path
import httpx
from mcp import ClientSession
from research_agent.mcp_compat import is_error, open_streams, structured


async def main():
    root = Path.home() / "Library/Application Support/prowl-research"
    origin = "http://127.0.0.1:18764"

    def usage_now():
        token = (root / "host.token").read_text().strip()
        return httpx.get(origin + "/fabric/v1/usage", headers={"Authorization": "Bearer " + token}, timeout=10).json()["days"]
    role = (Path.home() / ".config/agentgateway/secrets/roles/prowl").read_text().strip()
    async with open_streams("http://127.0.0.1:47845/mcp/prowl-research", {"x-agw-key": role}) as (r, w):
        async with ClientSession(r, w) as mcp:
            await mcp.initialize()
            # One key per smoke run: a fixed key returned an earlier smoke's completed job,
            # which then never showed input_required (per build was not enough: a second smoke
            # of one build hit the first one's job).
            build = httpx.get(origin + "/.well-known/fabric-service", timeout=5).json()["service"]["build"]["commit"][:12]
            build += "-" + time.strftime("%Y%m%dT%H%M%S", time.gmtime())
            # A tutorial adds no usage; real research runs may already have (B-081, 2026-10-25).
            before = usage_now()
            result = await mcp.call_tool(
                "research.tutorial",
                {
                    "idempotencyKey": "installed-" + build + "-tutorial",
                    "context": {
                        "requester": "Codex · проверка подключения",
                        "chain": "Учебная цепочка Fabric",
                        "node": "research",
                        "project": "Prowl — интеграция",
                    },
                },
                meta={"traceparent": "00-" + "a1" * 16 + "-" + "b2" * 8 + "-01"},
            )
            assert not is_error(result)
            job_id = structured(result)["job"]["id"]
            # B-100 (0.5.0): the free tutorial starts on the caller's allowance, no operator session needed.
            pending = structured(await mcp.call_tool("fabric.job.get", {"id": job_id}))["job"]
            assert pending["status"] in {"working", "completed"}, pending["status"]
            for _ in range(40):
                result = await mcp.call_tool("fabric.job.get", {"id": job_id})
                job = structured(result)["job"]
                if job["status"] == "completed":
                    break
                await asyncio.sleep(0.2)
            assert job["status"] == "completed"
            assert job["result"]["trace"]["traceparent"].split("-")[1] == "a1" * 16
            assert len(job["result"]["output"]["rows"]) == 3
            assert usage_now() == before, "the tutorial changed the usage report"
            print(
                json.dumps(
                    {
                        "status": "PASS",
                        "jobId": job_id,
                        "transport": "gateway → service MCP",
                        "decision": "synthetic tutorial started on the allowance (free)",
                        "tracePreserved": True,
                        "rows": 3,
                        "tutorialUsage": "unchanged",
                        "providerCalls": 0,
                    }
                )
            )


asyncio.run(main())
