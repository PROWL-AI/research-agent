#!/usr/bin/env python3
"""The cloud instance's operator commands (B-099 M5, M6).

  deploy   --app APP [--ref SHA]   test the commit's own tree, then build it on Heroku
  config   --app APP NAME...       copy named variables from this process's environment
                                   to the app's config vars; prints names only
  register --origin URL --token-file PATH
                                   write the remote Fabric descriptor prowl-research.cloud.json

The Heroku key is never an argument: run deploy and config under Observatory, e.g.
  python "$(project-observatory full-path)/tools/use_secret.py" run --env prod \\
      <project> HEROKU_API_KEY -- python scripts/cloud.py deploy --app prowl-research
and for config add the provider slots the app needs to the same `use_secret.py run`.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research_agent.service.identity import SERVICE_ID, SERVICE_NAME  # noqa: E402

API = "https://api.heroku.com"
ROOT = Path(__file__).resolve().parents[1]
SERVICES = Path.home() / "Library/Application Support/ai.passioncode.fabric/services"
#: Config vars the cloud instance may carry. Anything else is refused, so a stray
#: variable of the caller's environment never reaches the server.
CONFIG_NAMES = {"PROWL_API_KEY", "OPENROUTER_API_KEY", "RESEARCH_LLM_API_KEY", "FABRIC_SERVICE_TOKEN", "PUBLIC_ORIGIN",
                "RESEARCH_LLM_MODEL", "RESEARCH_LLM_BASE_URL"}


def headers(environ=os.environ):
    key = environ.get("HEROKU_API_KEY")
    if not key:
        raise SystemExit("HEROKU_API_KEY is not in the environment; run this under use_secret.py run")
    return {"Authorization": "Bearer " + key, "Accept": "application/vnd.heroku+json; version=3"}


def archive(ref: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar.gz", ref], check=True, capture_output=True).stdout


def gate(tarball: bytes, run=subprocess.run) -> None:
    """The commit's own tree must pass its suite before it is built: a deploy of an
    untested tree is refused (REQ-9)."""
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
            tar.extractall(tmp, filter="data")
        result = run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"], cwd=tmp,
                     env={**os.environ, "PYTHONPATH": tmp}, capture_output=True, text=True)
        if result.returncode != 0:
            tail = "\n".join(result.stdout.strip().splitlines()[-5:])
            raise SystemExit("refused: the commit's suite is not green\n" + tail)


def deploy(app: str, ref: str, client: httpx.Client, run=subprocess.run, sleep=time.sleep, out=print) -> dict:
    sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", ref], check=True, capture_output=True, text=True).stdout.strip()
    tarball = archive(sha)
    gate(tarball, run)
    source = client.post(f"{API}/apps/{app}/sources").raise_for_status().json()["source_blob"]
    httpx.put(source["put_url"], content=tarball, timeout=120).raise_for_status()
    build = client.post(f"{API}/apps/{app}/builds", json={"source_blob": {"url": source["get_url"], "version": sha}}).raise_for_status().json()
    out(f"build {build['id']} for {sha[:12]} started")
    while build["status"] == "pending":
        sleep(5)
        build = client.get(f"{API}/apps/{app}/builds/{build['id']}").raise_for_status().json()
    out(f"build {build['id']}: {build['status']}")
    if build["status"] != "succeeded":
        raise SystemExit(1)
    return build


def config(app: str, names: list[str], client: httpx.Client, environ=os.environ, out=print) -> None:
    unknown = sorted(set(names) - CONFIG_NAMES)
    if unknown:
        raise SystemExit("refused: not a config var of this service: " + ", ".join(unknown))
    missing = sorted(n for n in names if not environ.get(n))
    if missing:
        raise SystemExit("not in the environment: " + ", ".join(missing))
    client.patch(f"{API}/apps/{app}/config-vars", json={n: environ[n] for n in names}).raise_for_status()
    out("set: " + ", ".join(sorted(names)))


def descriptor(origin: str, token_file: Path) -> dict:
    parts = urlsplit(origin)
    if parts.scheme != "https" or parts.path not in {"", "/"} or parts.query or "@" in parts.netloc or not parts.hostname or "." not in parts.hostname:
        raise SystemExit("origin must be https://<public DNS name> without a path")
    return {
        "protocol": "fabric-service/0.1", "id": SERVICE_ID, "instance": "cloud", "name": f"{SERVICE_NAME} (cloud)",
        "summary": "The team's research gateway: runbooks and Prowl tools behind personal client keys",
        "placement": "remote", "origin": f"https://{parts.netloc}",
        "auth": {"tokenFile": str(token_file)}, "lifecycle": {"manager": "none"},
        "source": {"repository": "https://github.com/PROWL-AI/research-agent"},
        "peer": {"endpoint": f"https://{parts.netloc}/mcp", "custody": "organization-managed"},
        "installedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "installedBy": {"by": "person", "role": "operator", "tool": "prowl-research scripts/cloud.py register"},
    }


def register(origin: str, token_file: Path, services: Path = SERVICES, out=print) -> Path:
    token_file = Path(token_file).expanduser()
    mode = token_file.stat().st_mode & 0o777
    if mode != 0o600:
        raise SystemExit(f"the token file must be 0600, it is {oct(mode)}")
    services.mkdir(parents=True, exist_ok=True)
    target = services / f"{SERVICE_ID}.cloud.json"
    target.write_text(json.dumps(descriptor(origin, token_file), indent=1) + "\n")
    out(f"wrote {target}")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("deploy")
    d.add_argument("--app", required=True)
    d.add_argument("--ref", default="HEAD")
    c = sub.add_parser("config")
    c.add_argument("--app", required=True)
    c.add_argument("names", nargs="+")
    r = sub.add_parser("register")
    r.add_argument("--origin", required=True)
    r.add_argument("--token-file", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "register":
        register(args.origin, args.token_file)
        return
    with httpx.Client(headers=headers(), timeout=60) as client:
        if args.command == "deploy":
            deploy(args.app, args.ref, client)
        else:
            config(args.app, args.names, client)


if __name__ == "__main__":
    main()
