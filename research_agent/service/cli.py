"""Supervised service entry point. Installer owns descriptor and launchd plist."""
from __future__ import annotations
import argparse
import fcntl
import json
import os
import secrets
import stat
import sys
from pathlib import Path



def default_root():
    return Path.home() / "Library/Application Support/prowl-research" if sys.platform == "darwin" else Path.home() / ".local/share/prowl-research"


def lock(root):
    if root.is_symlink():
        raise ValueError("Data directory must not be a symlink")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(root / "service.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise SystemExit(75)
    root.chmod(0o700)
    return fd


def token(root, name):
    path = root / name
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w") as stream:
            stream.write(secrets.token_urlsafe(48))
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o600:
        raise ValueError("Token must be a regular owned 0600 file")
    return path.read_text().strip()


def main():
    parser = argparse.ArgumentParser(description="Prowl Research Fabric service")
    parser.add_argument("command", choices=["serve", "doctor"])
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--port", type=int, default=18764)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--build", type=Path)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    if args.command == "doctor":
        import httpx
        try:
            response = httpx.get(f"http://127.0.0.1:{args.port}/.well-known/fabric-service", timeout=3)
            response.raise_for_status()
            data = response.json()
            matched = data["service"]["id"] == "prowl-research" and data["service"]["instance"] == "default"
            print(json.dumps({"reachable": True, "identityMatches": matched, "health": data}, ensure_ascii=False))
            raise SystemExit(0 if matched else 1)
        except httpx.HTTPError as exc:
            print(json.dumps({"reachable": False, "error": type(exc).__name__}))
            raise SystemExit(1)
    fd = lock(args.root)
    os.umask(0o077)
    try:
        import uvicorn
        from .app import create_app
        build = json.loads(args.build.read_text()) if args.build else None
        app = create_app(args.root, token(args.root, "host.token"), token(args.root, "agent.token"), args.port, build)
        # Never log request URLs: the host's one-use login code is in its URL.
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning", timeout_graceful_shutdown=8)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
