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
from .identity import SERVICE_ID, SERVICE_NAME



def default_root():
    return Path.home() / "Library/Application Support/prowl-research" if sys.platform == "darwin" else Path.home() / ".local/share/prowl-research"


#: Event log rotation: five files of 5 MB — the structured events (run.*,
#: step.*, claim.*, budget.*, llm.budget) are INFO lines, secret-free by emit().
EVENT_LOG_BYTES = 5 * 1024 * 1024
EVENT_LOG_BACKUPS = 5


def default_log_dir():
    return Path.home() / "Library/Logs/prowl-research" if sys.platform == "darwin" else default_root() / "logs"


def configure_logging(log_dir):
    """INFO events to a size-capped rotating file of their own (B-035).

    launchd's stdout/stderr file keeps only what escapes Python logging
    (uvicorn warnings, a crash traceback): Python never rotates a file whose
    descriptor launchd holds, so the events do not go there."""
    import logging
    from logging.handlers import RotatingFileHandler

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    package = logging.getLogger("research_agent")
    target = str((log_dir / "events.log").resolve())
    for existing in list(package.handlers):
        # Idempotent: a second call must not double every line or rotate one
        # file from two handlers.
        if isinstance(existing, RotatingFileHandler) and existing.baseFilename == target:
            return log_dir / "events.log"
    handler = RotatingFileHandler(log_dir / "events.log", maxBytes=EVENT_LOG_BYTES,
                                  backupCount=EVENT_LOG_BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.setLevel(logging.INFO)
    package.setLevel(logging.INFO)
    package.addHandler(handler)
    package.propagate = False
    return log_dir / "events.log"


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


def cloud_root(environ=os.environ):
    return Path(environ.get("PROWL_RESEARCH_ROOT") or "/tmp/prowl-research")


def client_command(argv, environ=os.environ, out=print):
    """`client add|rotate|limit|revoke|list`: the cloud instance's client keys (B-099 M3, B-100).
    On Heroku: `heroku run prowl-research-service client add <name> --scopes read,tools.call --daily-usd 10`.
    `--raw` prints the key alone, for a pipe straight into the holder's vault slot (never into a transcript)."""
    from .clients import DAILY_FLOOR_USD, SCOPES, from_env

    parser = argparse.ArgumentParser(prog="prowl-research-service client")
    parser.add_argument("action", choices=["add", "rotate", "limit", "revoke", "list"])
    parser.add_argument("name", nargs="?")
    parser.add_argument("--scopes", default="read", help="comma-separated: " + ", ".join(SCOPES))
    parser.add_argument("--daily-usd", type=float, default=DAILY_FLOOR_USD,
                        help=f"the key's ceiling per UTC day, at least {DAILY_FLOOR_USD:g} (B-100)")
    parser.add_argument("--raw", action="store_true", help="print only the key, for a pipe into a vault")
    args = parser.parse_args(argv)
    clients = from_env(cloud_root(environ), environ)
    if args.action == "list":
        out(json.dumps(clients.list(), ensure_ascii=False, indent=1))
        return 0
    if not args.name:
        parser.error("a client name is required")
    if args.action == "revoke":
        clients.revoke(args.name)
        out(f"revoked {args.name}")
        return 0
    if args.action == "limit":
        clients.limit(args.name, args.daily_usd)
        out(f"{args.name}: daily ceiling {args.daily_usd:g} USD")
        return 0
    key = clients.add(args.name, args.scopes.split(","), args.daily_usd) if args.action == "add" else clients.rotate(args.name)
    # The one time the key is shown: it is not stored, only its SHA-256.
    if args.raw:
        out(key)
        return 0
    out(f"{args.name}: {key}")
    out("Shown once. Give it to its holder privately; it is never shown again.")
    return 0


def cloud_run(environ=os.environ):
    """The cloud instance (B-099): Heroku's $PORT on all interfaces, its own https
    origin only, client keys on /mcp, state restored from and saved to Postgres."""
    import logging
    import threading
    import uvicorn
    from .app import CloudSettings, create_app
    from .clients import from_env as clients_from_env
    from .snapshot import from_env as snapshots_from_env

    origin = environ.get("PUBLIC_ORIGIN", "")
    token_value = environ.get("FABRIC_SERVICE_TOKEN", "")
    if not origin.startswith("https://") or origin.count("/") != 2:
        raise SystemExit("PUBLIC_ORIGIN must be https://<host> without a path")
    if len(token_value) < 32:
        raise SystemExit("FABRIC_SERVICE_TOKEN must be set (at least 32 characters)")
    port = int(environ.get("PORT", "8000"))
    root = cloud_root(environ)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    snapshots = snapshots_from_env(environ)
    if snapshots is not None:
        snapshots.restore(root)
    fd = lock(root)
    os.umask(0o077)
    stop = threading.Event()

    def keep():
        while not stop.wait(30):
            try:
                snapshots.save(root)
            except Exception as exc:  # noqa: BLE001 — logged by name, retried in 30 s
                logging.getLogger("research_agent.service.snapshot").warning("event=snapshot.failed error=%s", type(exc).__name__)

    try:
        # Heroku names the deployed commit; without it the code digest is computed as locally.
        build = {"digest": "git:" + environ["SOURCE_VERSION"]} if environ.get("SOURCE_VERSION") else None
        app = create_app(root, token_value, None, port, build, cloud=CloudSettings(origin=origin, clients=clients_from_env(root, environ)))
        if snapshots is not None:
            threading.Thread(target=keep, name="snapshot", daemon=True).start()
        uvicorn.run(app, host="0.0.0.0", port=port, access_log=False, log_level="warning", timeout_graceful_shutdown=8,
                    proxy_headers=False)
    finally:
        stop.set()
        if snapshots is not None:
            snapshots.save(root)
        os.close(fd)


def main():
    if sys.argv[1:2] == ["client"]:
        raise SystemExit(client_command(sys.argv[2:]))
    if sys.argv[1:2] == ["cloud-run"]:
        return cloud_run()
    parser = argparse.ArgumentParser(description=f"{SERVICE_NAME} Fabric service")
    parser.add_argument("command", choices=["serve", "doctor"])
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--port", type=int, default=18764)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--build", type=Path)
    parser.add_argument("--log-dir", type=Path, default=default_log_dir())
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    if args.command == "doctor":
        import httpx
        try:
            response = httpx.get(f"http://127.0.0.1:{args.port}/.well-known/fabric-service", timeout=3)
            response.raise_for_status()
            data = response.json()
            matched = data["service"]["id"] == SERVICE_ID and data["service"]["instance"] == "default"
            print(json.dumps({"reachable": True, "identityMatches": matched, "health": data,
                              "eventLog": str(args.log_dir / "events.log")}, ensure_ascii=False))
            raise SystemExit(0 if matched else 1)
        except httpx.HTTPError as exc:
            print(json.dumps({"reachable": False, "error": type(exc).__name__}))
            raise SystemExit(1)
    fd = lock(args.root)
    os.umask(0o077)
    configure_logging(args.log_dir)
    try:
        import uvicorn
        from .app import create_app
        build = json.loads(args.build.read_text()) if args.build else None
        app = create_app(args.root, token(args.root, "host.token"), token(args.root, "agent.token"), args.port, build)
        # Never log request URLs: the host's one-use login code is in its URL.
        # Loopback only: the dashboard login and the own-token tier (T0) assume it.
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning", timeout_graceful_shutdown=8)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
