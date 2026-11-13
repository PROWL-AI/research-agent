#!/usr/bin/env python3
"""Claude Code's `headersHelper` for a local Prowl Research service (B-106).

Prints `{"Authorization": "Bearer <agent token>"}` read from the service's own agent token file, so the token never
goes into a client configuration, an argument or a log: Claude Code runs this when it connects and keeps the answer in
memory. Only this account can read the file (0600 in a 0700 folder), which is what proves the caller is the service's
own account on a Mac whose loopback other accounts share. A missing or unreadable file prints nothing and exits 1,
so the client fails to connect instead of connecting without a token.

    claude mcp add-json prowl-research '{"type":"http","url":"http://127.0.0.1:<port>/mcp",
      "headersHelper":"/usr/bin/python3 <checkout>/scripts/mcp_headers.py"}' -s user
"""

import json
import os
import stat
import sys
from pathlib import Path

DEFAULT_ROOT = Path.home() / "Library/Application Support/prowl-research"


def headers(root: Path = DEFAULT_ROOT) -> dict[str, str]:
    path = root / "agent.token"
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
        raise PermissionError(f"{path} is not a private file of this account")
    token = path.read_text().strip()
    if not token:
        raise ValueError(f"{path} is empty")
    return {"Authorization": f"Bearer {token}"}


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else DEFAULT_ROOT
    try:
        print(json.dumps(headers(root)))
    except (OSError, ValueError) as exc:
        print(f"prowl-research headers: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
