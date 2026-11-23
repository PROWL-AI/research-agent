#!/usr/bin/env python3
"""Run a one-off command on a Heroku app with the Observatory `deploy` key and print its output (B-160).

The Heroku CLI's `heroku run` reads `/account` first, which the `deploy` key (scopes read, write) may not: it answers
"Couldn't find that user". The Platform API's `POST /apps/<app>/dynos` with `attach: true` accepts the same key; the
dyno's terminal is then read from the rendezvous URL it answers (TLS, the URL's path as the first line).

    use_secret.py run --vault-only --env prod <folder> HEROKU_API_KEY -- \
        python scripts/heroku_run.py <app> "prowl-research-service client list"

The key is read from `HEROKU_API_KEY` in the environment, never from argv, and is never printed. Exit 0 when the
dyno was created and its output read to the end; 1 when Heroku refused the dyno.
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.heroku.com"


def create_dyno(app: str, command: str, token: str) -> str:
    body = json.dumps({"command": command, "attach": True, "type": "run"}).encode()
    request = urllib.request.Request(f"{API}/apps/{urllib.parse.quote(app)}/dynos", data=body, method="POST", headers={
        "Authorization": "Bearer " + token, "Accept": "application/vnd.heroku+json; version=3",
        "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as answer:
        return json.load(answer)["attach_url"]


def read_rendezvous(url: str, timeout: float = 600.0) -> bytes:
    parsed = urllib.parse.urlparse(url)
    context = ssl.create_default_context()
    with socket.create_connection((parsed.hostname, parsed.port or 5000), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=parsed.hostname) as stream:
            stream.sendall((parsed.path.lstrip("/") + "\r\n").encode())
            chunks = []
            while True:
                chunk = stream.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
    output = b"".join(chunks)
    return output[len(b"rendezvous\r\n"):] if output.startswith(b"rendezvous\r\n") else output


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: heroku_run.py <app> <command>", file=sys.stderr)
        return 2
    token = os.environ.get("HEROKU_API_KEY", "")
    if not token:
        print("HEROKU_API_KEY is not set: run under use_secret.py", file=sys.stderr)
        return 2
    try:
        url = create_dyno(argv[0], argv[1], token)
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode(errors="replace")
        print(f"Heroku refused the dyno: {exc.code} {detail}", file=sys.stderr)
        return 1
    sys.stdout.write(read_rendezvous(url).decode(errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
