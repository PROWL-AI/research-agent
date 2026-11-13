"""scripts/configure_service.py changes a running service's settings through its own API (login code, session, the
form's revision check), so nobody presses the dashboard's button."""
import importlib.util
from pathlib import Path

import httpx

from research_agent.service.app import create_app

ROOT = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("configure_service", ROOT / "scripts" / "configure_service.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_types_the_numbers():
    assert _script().parse(["strong_model=moonshotai/kimi-k3.1-pro", "agent_daily_usd=12.5", "max_workers=2"]) == {
        "strong_model": "moonshotai/kimi-k3.1-pro", "agent_daily_usd": 12.5, "max_workers": 2}


async def test_settings_change_through_the_api(tmp_path):
    """The same steps `configure` takes (login code, session, state, config with the revision), over ASGI."""
    app = create_app(tmp_path, "host-value", None)
    mod = _script()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:18764", follow_redirects=False) as c:
        code = await c.post("/fabric/v1/login-code", headers={"Authorization": "Bearer host-value"})
        assert code.status_code == 200
        login = await c.get(code.json()["url"])
        assert login.status_code in (302, 303)
        current = (await c.get("/api/state")).json()["config"]
        values = {k: v for k, v in current.items() if k != "revision"} | mod.parse(["strong_model=moonshotai/kimi-k3.1-pro"])
        saved = await c.post("/api/config", headers={"X-Prowl-Request": "1"}, json={"revision": current["revision"], "values": values})
        assert saved.status_code == 200 and saved.json()["strong_model"] == "moonshotai/kimi-k3.1-pro"
    await app.state.runtime.close()
