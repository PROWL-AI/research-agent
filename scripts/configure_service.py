#!/usr/bin/env python3
"""Change a running Prowl Research's settings through its own API, as the dashboard's settings form does.

The operator presses nothing (rule of 2026-11-07): the service token opens a one-time login code, the session it
gives saves the settings for new requests (the same check of the revision as the form). Old requests keep their
snapshot. The token is read from a 0600 file and never printed.

    python scripts/configure_service.py --origin http://127.0.0.1:18764 \\
        --token-file "~/Library/Application Support/prowl-research/host.token" --set strong_model=moonshotai/kimi-k3.1-pro
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

NUMBERS = {"parallel_jobs": int, "max_workers": int, "timeout_minutes": int, "agent_daily_usd": float}


def parse(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        if not key or not _:
            raise SystemExit(f"--set takes name=value, got {pair!r}")
        out[key] = NUMBERS.get(key, str)(value)
    return out


def configure(origin: str, token: str, changes: dict, client: httpx.Client | None = None) -> dict:
    client = client or httpx.Client(base_url=origin, follow_redirects=False, timeout=30, headers={"x-forwarded-proto": "https"} if origin.startswith("https") else {})
    code = client.post("/fabric/v1/login-code", headers={"Authorization": "Bearer " + token})
    code.raise_for_status()
    login = client.get(code.json()["url"])
    if login.status_code not in (302, 303):
        raise SystemExit(f"login refused: HTTP {login.status_code}")
    current = client.get("/api/state").json()["config"]
    values = {k: v for k, v in current.items() if k != "revision"} | changes
    saved = client.post("/api/config", headers={"X-Prowl-Request": "1"}, json={"revision": current["revision"], "values": values})
    saved.raise_for_status()
    return {"before": {k: current.get(k) for k in changes}, "after": {k: saved.json().get(k) for k in changes},
            "revision": saved.json()["revision"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--origin", required=True)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--set", action="append", default=[], required=True, help="name=value, repeatable")
    args = parser.parse_args(argv)
    token = args.token_file.expanduser().read_text().strip()
    print(json.dumps(configure(args.origin.rstrip("/"), token, parse(args.set)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
