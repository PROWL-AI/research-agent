#!/usr/bin/env python3
"""Install a clean committed snapshot; no provider keys or agent config edits.

With --vault-project NAME the service is launched through Project Observatory's
vault-only service consumer: `use_secret.py serve --env prod --consumer
chat.prowl.research NAME PROWL_API_KEY,RESEARCH_LLM_API_KEY -- <serve>`, run by
Observatory's own interpreter. The keys live in the vault, reach the process
environment only, and never touch the plist, argv, a file or a log. Without it
the service starts degraded (no provider keys) and says so. Delegation settings
(RESEARCH_DELEGATION_ISSUER/_JWKS/_AUDIENCE) present in the installer's
environment are passed to the service; they are public configuration, not keys.
A folder holding only some slots launches with those (the service is degraded
for the missing provider and says so); a folder holding none is refused.
--dry-run prints the launch argv and the slots it needs, installs nothing.

--background (B-106) is for a space of a shared Mac with no GUI login (the Mac Studio): launchd has no `gui/<uid>`
there, so the definition goes into the space's background folder, where Observatory's `observatory-space-daemons`
turns it into a system daemon that runs as the account (`UserName`), never as root. The label carries the account
(`chat.prowl.research.<account>`), since every space shares one /Library/LaunchDaemons; the port is the space's own,
since every space shares one loopback. The installer loads it through studio-agent's door
`sudo -n studio-space-service deploy <label>` (DEC-0033); before the administrator's first `apply` there is no daemon to
replace, and the installer exits 77 with the line that loads it.
"""

import argparse
import fcntl
import json
import os
import plistlib
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "prowl-research"
LABEL = "chat.prowl.research"
#: The provider keys the service needs, by vault slot name (never a value).
SLOTS = ("PROWL_API_KEY", "RESEARCH_LLM_API_KEY")
#: B-106: a space without a GUI login. Observatory reads this folder under the home folder only.
BACKGROUND_DIR = (".local", "share", "project-observatory", "background", "LaunchAgents")
SPACE_DOOR = "/usr/local/libexec/studio-space-service"
SPACE_DAEMONS = "/usr/local/libexec/observatory-space-daemons"
#: The definition is written and the release built; the administrator's first `apply` loads it.
FIRST_APPLY = 77


def command(*args, **kw):
    return subprocess.check_output(args, text=True, **kw).strip()


def atomic(path, body):
    temp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(body)
    os.replace(temp, path)


def observatory_python(engine):
    """The interpreter of the virtualenv Observatory's engine is installed in."""
    for parent in engine.parents:
        if (parent / "pyvenv.cfg").is_file() and (parent / "bin/python").exists():
            return str(parent / "bin/python")
    return sys.executable


def missing_slots(project):
    """Slots the vault folder lacks (names only — a value is never read here).
    A listing line is `  <folder>/<env>/<NAME>  (<size>…)`: matched exactly."""
    engine = Path(command("project-observatory", "full-path"))
    listing = command(observatory_python(engine), str(engine / "tools/vault.py"), "list", project, "prod")
    held = {line.split()[0] for line in listing.splitlines() if line.strip() and "/" in line.split()[0]}
    return [s for s in SLOTS if f"{project}/prod/{s}" not in held]


def vault_consumer(project, slots=SLOTS):
    """The Observatory vault-only service consumer's argv prefix, for the slots the folder holds."""
    engine = Path(command("project-observatory", "full-path"))
    return [
        observatory_python(engine),
        str(engine / "tools/use_secret.py"),
        "serve",
        "--env",
        "prod",
        "--consumer",
        LABEL,
        project,
        ",".join(slots),
        "--",
    ]


#: Public delegation configuration passed through to the service (never a key).
DELEGATION_ENV = ("RESEARCH_DELEGATION_ISSUER", "RESEARCH_DELEGATION_JWKS", "RESEARCH_DELEGATION_AUDIENCE")


def launch_argv(python, data, port, build, logs, vault_project, slots=SLOTS):
    serve = [
        python,
        "-m",
        "research_agent.service.cli",
        "serve",
        "--root",
        str(data),
        "--port",
        str(port),
        "--build",
        str(build),
        "--log-dir",
        str(logs),
    ]
    return (vault_consumer(vault_project, slots) + serve) if vault_project else serve


def slot_check(project):
    """(held, missing, problem): the slots to launch with — those the folder holds.
    A missing one leaves the service degraded (it says which provider is absent);
    `problem` names why an install must not proceed (none held, check failed)."""
    try:
        missing = missing_slots(project)
    except subprocess.CalledProcessError as exc:
        return [], list(SLOTS), f"vault {project}: the slot check failed (exit {exc.returncode}); resolve the folder in Observatory first"
    except FileNotFoundError as exc:
        # project-observatory itself, or the interpreter its engine is installed with
        return [], list(SLOTS), f"cannot run the Observatory vault check ({exc.filename or exc}); install or repair Project Observatory first"
    held = [s for s in SLOTS if s not in missing]
    problem = None if held else f"vault {project}/prod holds none of {', '.join(SLOTS)}: issue them through Observatory's doors first"
    return held, missing, problem


def held_slots(project, p):
    held, missing, problem = slot_check(project)
    if problem:
        p.error(problem)
    return held, missing


def space_user():
    """The account's name, as Observatory's command takes it; one the user database does not name is its uid."""
    import pwd

    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return str(os.getuid())


def background_label(user):
    """One system daemon per space: every space of the machine shares /Library/LaunchDaemons."""
    return f"{LABEL}.{user}"


def first_apply_line(user, label):
    return f"sudo /usr/bin/python3 -I {SPACE_DAEMONS} apply --user {user} --label {label}"


def background_definition(payload, label, home):
    """The plist a space daemon runs: its own label, HOME and a PATH that reaches Homebrew and the account's tools (a
    system daemon starts with neither), the vault in vault-only mode; output goes to the service's own log folder."""
    doc = dict(payload, Label=label)
    doc.pop("StandardOutPath", None)
    doc.pop("StandardErrorPath", None)
    env = dict(doc.get("EnvironmentVariables") or {})
    env.update({"HOME": str(home), "OBSERVATORY_VAULT_ONLY": "1",
                "PATH": f"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:{home}/.local/bin"})
    doc["EnvironmentVariables"] = env
    return doc


def port_answers(port, timeout=1.0):
    """Whether something listens on the loopback port (on a shared Mac, maybe another space's service)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def door_deploy(label, run=subprocess.run):
    """Load the space's changed definition through studio-agent's door. ("loaded" | "first-apply", door output)."""
    try:
        r = run(["sudo", "-n", SPACE_DOOR, "deploy", label], capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"the space door {SPACE_DOOR} did not run: {exc}") from exc
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode == 0:
        return "loaded", out
    if r.returncode == 3:  # not-installed: no system daemon yet
        return "first-apply", out
    raise RuntimeError(f"the space door refused deploy {label} (exit {r.returncode}): {out[-400:]}")


def strip_build_output(source: Path) -> list[str]:
    """Remove build output the archive may carry: setuptools installs a stale ``build/lib`` in place of the
    sources it sits beside (0.3.0 and 0.3.1 shipped one). Returns what was removed."""
    removed = []
    for path in [source / "build", *source.glob("*.egg-info")]:
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(path.name)
    return removed


#: A wall-clock deadline, not a count of tries: under a load average near 1000 (2026-10-24) a good
#: install answered after the old 480 tries of 0.25 s had run out (B-093).
READY_TIMEOUT_S = 600.0


def wait_ready(origin: str, sha: str, timeout_s: float, *, clock=time.monotonic, sleep=time.sleep) -> bool:
    """True once ``origin`` answers its well-known document on commit ``sha``, False at the deadline."""
    deadline = clock() + timeout_s
    while True:
        try:
            with urllib.request.urlopen(origin + "/.well-known/fabric-service", timeout=3) as r:
                if json.load(r)["service"]["build"].get("commit") == sha:
                    return True
        except Exception:  # noqa: BLE001 — not up yet, or still the previous release
            pass
        if clock() >= deadline:
            return False
        sleep(0.25)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=18764)
    p.add_argument("--vault-project", help="Observatory vault folder holding the service's keys (prod slots %s)" % ", ".join(SLOTS))
    p.add_argument("--dry-run", action="store_true", help="print the launch argv and the slots it needs; install nothing")
    p.add_argument("--background", action="store_true",
                   help="a space with no GUI login (Mac Studio): a system daemon run as this account, loaded through "
                        "studio-agent's door (B-106); give the space its own --port")
    p.add_argument("--ready-timeout", type=float, default=READY_TIMEOUT_S,
                   help="seconds to wait for the service to answer on the new commit (default %(default)s)")
    a = p.parse_args()
    if sys.platform != "darwin":
        p.error("This installer supports macOS launchd; manual foreground serve is portable.")
    if a.dry_run:
        base = Path.home() / ".local/share" / ID
        held, missing, problem = slot_check(a.vault_project) if a.vault_project else ([], [], None)
        try:
            argv = launch_argv(
                str(base / "releases/<commit>/venv/bin/python"),
                Path.home() / "Library/Application Support" / ID,
                a.port,
                base / "releases/<commit>/build.json",
                Path.home() / "Library/Logs" / ID,
                a.vault_project,
                held,
            )
        except FileNotFoundError:
            argv = None  # no Observatory engine to name; `problem` says so
        print(
            json.dumps(
                {
                    "argv": argv,
                    "slots": held,
                    "missing": missing,
                    "problem": problem,
                    "keys": "vault-only consumer" if a.vault_project else "none: the service starts degraded",
                },
                indent=2,
            )
        )
        if problem:
            raise SystemExit(2)  # the real install would refuse: say so in the exit code too
        return
    held, missing = held_slots(a.vault_project, p) if a.vault_project else ([], [])
    if missing:
        print(f"warning: vault {a.vault_project}/prod lacks {', '.join(missing)}; the service starts degraded without it", file=sys.stderr)
    if command("git", "status", "--porcelain", cwd=ROOT):
        p.error("Commit task changes before immutable installation.")
    sha = command("git", "rev-parse", "HEAD", cwd=ROOT)
    base = Path.home() / ".local/share" / ID
    release = base / "releases" / sha[:12]
    registry = Path.home() / "Library/Application Support/ai.passioncode.fabric/services"
    registry.mkdir(parents=True, exist_ok=True)
    with open(registry / ".prowl-install.lock", "a") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        for path in registry.glob("*.json"):
            d = json.loads(path.read_text())
            if d.get("origin") == f"http://127.0.0.1:{a.port}" and (d.get("id"), d.get("instance")) != (ID, "default"):
                p.error("Port already claimed by " + path.name)
        target = registry / (ID + ".default.json")
        own = json.loads(target.read_text()) if target.exists() else None
        if own is not None and own.get("installedBy") != "prowl-research-service":
            p.error("Existing descriptor belongs to another installer")
        if port_answers(a.port) and (own or {}).get("origin") != f"http://127.0.0.1:{a.port}":
            # On a shared Mac loopback is shared too: another space's service may hold the port (B-106).
            p.error(f"Port {a.port} already answers and this account's descriptor does not claim it; choose a free --port")
        if not release.exists():
            release.mkdir(parents=True)
            try:
                with tempfile.TemporaryFile() as archive:
                    subprocess.run(["git", "archive", sha], cwd=ROOT, stdout=archive, check=True)
                    archive.seek(0)
                    with tarfile.open(fileobj=archive) as tar:
                        tar.extractall(release / "source", filter="data")
                strip_build_output(release / "source")
                uv = shutil.which("uv")
                if not uv:
                    raise RuntimeError("uv is required; install it explicitly before running this installer")
                subprocess.run([uv, "venv", "--python", "3.11", str(release / "venv")], check=True)
                subprocess.run([uv, "pip", "install", "--python", str(release / "venv/bin/python"), str(release / "source")], check=True)
                (release / "build.json").write_text(json.dumps({"commit": sha, "dirty": False}))
            except BaseException:
                shutil.rmtree(release)
                raise
        data = Path.home() / "Library/Application Support" / ID
        logs = Path.home() / "Library/Logs" / ID
        logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        user = space_user()
        label = background_label(user) if a.background else LABEL
        plist = (Path.home().joinpath(*BACKGROUND_DIR) if a.background else Path.home() / "Library/LaunchAgents") / f"{label}.plist"
        python = str(release / "venv/bin/python")
        argv = launch_argv(python, data, a.port, release / "build.json", logs, a.vault_project, held)
        payload = {
            "Label": LABEL,
            "ProgramArguments": argv,
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": 10,
            "ExitTimeOut": 15,
            "ProcessType": "Standard",
            "EnvironmentVariables": {
                "PATH": "/usr/bin:/bin:/usr/local/bin",
                "FABRIC_SERVICE_SUPERVISOR": "launchd",
                **{k: os.environ[k] for k in DELEGATION_ENV if os.environ.get(k)},
            },
            "StandardOutPath": str(logs / "service.log"),
            "StandardErrorPath": str(logs / "service.log"),
        }
        if a.background:
            payload = background_definition(payload, label, Path.home())
            disabled = False
        else:
            domain = f"gui/{os.getuid()}"
            overrides = command("launchctl", "print-disabled", domain)
            disabled = f'"{LABEL}" => disabled' in overrides
            # Stop only this owned label and wait; never disturb unrelated research agents.
            subprocess.run(["launchctl", "bootout", domain + "/" + LABEL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(50):
                if subprocess.run(["launchctl", "print", domain + "/" + LABEL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("Previous service did not stop; installation left unchanged")
        plist.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic(plist, plistlib.dumps(payload))
        subprocess.run(["plutil", "-lint", str(plist)], check=True)
        descriptor = {
            "protocol": "fabric-service/0.1",
            "id": ID,
            "instance": "default",
            "name": "Prowl Research",
            "summary": "Research requests, evidence, costs and human decisions",
            "origin": f"http://127.0.0.1:{a.port}",
            "auth": {"tokenFile": str(data / "host.token")},
            "lifecycle": ({"manager": "launchd", "domain": "system", "label": label, "plist": str(plist),
                           "control": f"sudo -n {SPACE_DOOR} <start|stop|restart|status|deploy> {label}"}
                          if a.background else {"manager": "launchd", "label": LABEL, "plist": str(plist)}),
            # A space daemon has no stdout file (Observatory's definition carries none): the service's own log only.
            "paths": {"data": str(data), "config": str(data),
                      "logs": [str(logs / "events.log")] + ([] if a.background else [str(logs / "service.log")])},
            "commands": {"doctor": [python, "-m", "research_agent.service.cli", "doctor", "--port", str(a.port), "--json"]},
            "source": {"repository": "https://github.com/PROWL-AI/research-agent"},
            "fabricManifest": str(release / "source/fabric-agent.json"),
            "installedAt": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "installedBy": "prowl-research-service",
        }
        atomic(target, (json.dumps(descriptor, indent=2) + "\n").encode())
        loaded = "first-apply"
        if a.background:
            loaded, door = door_deploy(label)
        elif not disabled:
            subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
            loaded = "loaded"
        if loaded == "loaded" and not wait_ready(descriptor["origin"], sha, a.ready_timeout):
            raise RuntimeError(
                f"Service did not answer on commit {sha[:12]} within {a.ready_timeout:g} s; the release and its "
                f"descriptor are installed and launchd keeps starting it. Check: curl -s "
                f"{descriptor['origin']}/.well-known/fabric-service (a loaded machine can take longer; "
                f"--ready-timeout raises the wait)")
        if a.background and loaded == "first-apply":
            print(json.dumps({"descriptor": str(target), "commit": sha, "release": str(release), "plist": str(plist),
                              "label": label, "firstApply": first_apply_line(user, label), "door": door}))
            raise SystemExit(FIRST_APPLY)
        print(json.dumps({"descriptor": str(target), "commit": sha, "disabled": disabled, "release": str(release)}))
        # Retain current + previous release. Only directories made by this installer.
        others = sorted(
            [x for x in (base / "releases").iterdir() if x != release and (x / "build.json").is_file()], key=lambda x: x.stat().st_mtime, reverse=True
        )
        for old in others[1:]:
            shutil.rmtree(old)


if __name__ == "__main__":
    main()
