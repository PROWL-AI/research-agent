#!/usr/bin/env python3
"""Build the team copy of Prowl Research (B-099 M7, D15).

The copy `appvillis-com/appvillis-prowl-research` is built only from a named commit of this
repository; nobody edits it by hand. One flow, original to copy:

    scripts/build_team_copy.py --ref <sha> --copy <clone of the copy> [--audit <org-transfer-audit>] [--org <org>]

`--org` names the organization (B-115): `appvillis` (the default, `appvillis-com/appvillis-prowl-research`) or
`passioncode`; each copy carries its organization's prefix in its id, its name and its builder identity.

1. Refuses when the copy holds a commit after its last build that is not the builder's
   and is not named by a `Backports: <sha>` line in the original up to `--ref` (S3).
2. Writes the commit's tree without the paths that stay with the original (run
   evidence, reports, the handoff log), plus `.copy/upstream.json`; the LICENSE is the
   original's, byte for byte (D14, B-099 R-2).
3. Runs the org-transfer audit on the built tree when `--audit` names it, and refuses
   anything but `ready`.
4. Commits on branch `sync/<sha12>` as the builder, with `Source-Revision`. Moving the
   copy's `main` is a fast-forward push of that branch after its checks; the command is
   printed, never run here.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
ALIAS = "prowl-research"


class Org(NamedTuple):
    """An organization's copy (B-115): its id prefix, its display name and its header."""

    prefix: str
    name: str

    @property
    def copy_id(self) -> str:
        return f"{self.prefix}-{ALIAS}"

    @property
    def copy_name(self) -> str:
        return f"{self.name} Prowl Research"

    @property
    def author(self) -> tuple[str, str]:
        return (self.copy_id, f"{self.copy_id}@users.noreply.github.com")

    @property
    def identity(self) -> str:
        return (f'''"""Who this service is, in one place: the {self.name} team copy (written by the builder)."""

SERVICE_ID = "{self.copy_id}"
SERVICE_NAME = "{self.copy_name}"
HEADER = "{self.prefix.upper()} · PROWL · Research"
''')


#: The operator's organizations a copy is built for: the copy's id carries the prefix and its name the
#: organization (operator, 2026-11-04); the original keeps none.
ORGS = {"appvillis": Org("appvillis", "Appvillis"), "passioncode": Org("passioncode", "PassionCode")}
DEFAULT_ORG = ORGS["appvillis"]
AUTHOR = DEFAULT_ORG.author
#: What stays with the original: the operator's run evidence and reports, the session
#: handoff log, pipeline state. The code, runbooks, specs and user docs travel.
FORBIDDEN = ("docs/evidence/", "docs/reports/", "docs/HANDOFF.md", "runs/", ".task-pipeline/", "node_modules/")


#: The default copy's names, kept for callers of the Appvillis builder.
COPY_ID = DEFAULT_ORG.copy_id
COPY_NAME = DEFAULT_ORG.copy_name
IDENTITY = DEFAULT_ORG.identity
#: Team-facing documents name the copy's service, app and MCP server, never the original's.
RENAMED_DOCS = ("docs/CLOUD.md", "docs/TEAM-ONBOARDING.md")
ORIGINAL_ID = re.compile(r"(?<![\w/@-])prowl-research(?![\w-])")


def rename(files: dict[str, bytes], org: Org = DEFAULT_ORG) -> dict[str, bytes]:
    files = dict(files)
    files["research_agent/service/identity.py"] = org.identity.encode()
    for name in RENAMED_DOCS:
        if name in files:
            files[name] = ORIGINAL_ID.sub(org.copy_id, files[name].decode()).encode()
    if "README.md" in files:
        text = files["README.md"].decode()
        files["README.md"] = re.sub(r"^# ", f"# {org.copy_name}: ", text, count=1).encode()
    return files


def git(repo, *args, text=True):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=text).stdout


def last_build(copy: Path, org: Org = DEFAULT_ORG) -> tuple[str | None, list[str]]:
    """The copy's last build commit and the commits after it, newest first."""
    try:
        log = git(copy, "log", "--format=%H%x09%ae%x09%B%x1e")
    except subprocess.CalledProcessError:
        return None, []
    after = []
    for entry in filter(None, (e.strip() for e in log.split("\x1e"))):
        sha, email, body = entry.split("\t", 2)
        if email == org.author[1] and f"Source-Revision: {ALIAS}@" in body:
            return sha, after
        after.append(sha)
    return None, after


def unported(copy: Path, ref: str, after: list[str], root: Path = ROOT, org: Org = DEFAULT_ORG) -> list[str]:
    """Commits in the copy after its last build that are neither the builder's own nor
    named by a `Backports:` line of the original up to `ref` (D15 S3)."""
    backports = git(root, "log", "--format=%B", ref)
    named = {w for line in backports.splitlines() if line.startswith("Backports:") for w in line.split()[1:]}
    own = set(git(copy, "log", "--format=%H", f"--author={org.author[1]}").split()) if after else set()
    return [sha for sha in after if sha not in own and not any(sha.startswith(n) for n in named)]


def tree(ref: str, root: Path = ROOT) -> dict[str, bytes]:
    data = git(root, "archive", "--format=tar", ref, text=False)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar.getmembers():
            if member.isfile() and not member.name.startswith(FORBIDDEN):
                files[member.name] = tar.extractfile(member).read()
    return files


def build(ref: str, copy: Path, audit: Path | None = None, out=print, root: Path = ROOT, org: Org = DEFAULT_ORG) -> str:
    sha = git(root, "rev-parse", ref).strip()
    previous, after = last_build(copy, org)
    # Before the first build there is nothing to port: the copy holds only its creation.
    blocked = unported(copy, sha, after, root, org) if previous else []
    if blocked:
        raise SystemExit("refused: copy commits not ported to the original (add `Backports: <sha>` there first): "
                         + ", ".join(b[:12] for b in blocked))
    files = rename(tree(sha, root), org)
    if "LICENSE" not in files:
        raise SystemExit("refused: the commit has no LICENSE")
    marker = copy / ".copy/upstream.json"
    before = json.loads(marker.read_text())["sourceRevision"] if previous and marker.exists() else None
    branch = f"sync/{sha[:12]}"
    git(copy, "checkout", "-q", "-B", branch)
    for path in git(copy, "ls-files", "-z").split("\0"):
        if path:
            (copy / path).unlink(missing_ok=True)
    for name, body in files.items():
        target = copy / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    upstream = {"kind": "export", "source": ALIAS, "sourceRevision": sha,
                "previousRevision": before,
                "builtAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "builder": "scripts/build_team_copy.py", "forbidden": list(FORBIDDEN)}
    (copy / ".copy").mkdir(exist_ok=True)
    (copy / ".copy/upstream.json").write_text(json.dumps(upstream, indent=1) + "\n")
    leaked = [n for n in git(copy, "ls-files", "--others", "--cached", "--exclude-standard").splitlines() if n.startswith(FORBIDDEN)]
    if leaked:
        raise SystemExit("refused: forbidden paths in the copy: " + ", ".join(leaked[:5]))
    git(copy, "add", "-A")
    count = len(git(root, "rev-list", f"{upstream['previousRevision']}..{sha}").split()) if upstream["previousRevision"] else None
    message = (f"chore(copy): sync with the original at {sha[:12]}" + (f" ({count} commits)" if count else "")
               + f"\n\nSource-Revision: {ALIAS}@{sha}\n")
    subprocess.run(["git", "-C", str(copy), "-c", f"user.name={org.author[0]}", "-c", f"user.email={org.author[1]}",
                    "commit", "-q", "--allow-empty", "-m", message], check=True)
    # The audit reads a committed tree, so it runs on the build commit; a refused build
    # stays on its local branch, which is never pushed.
    if audit is not None:
        result = subprocess.run(["python3", str(audit), str(copy), "--no-history", "--json"], capture_output=True, text=True)
        try:
            verdict = json.loads(result.stdout).get("verdict")
        except ValueError:
            verdict = None
        if verdict != "ready":
            raise SystemExit(f"refused: org-transfer audit verdict {verdict!r} on {branch}; do not push it")
    out(f"built {branch} in {copy}")
    out(f"after its checks: git -C {copy} push origin {branch}:main  (fast-forward only)")
    return branch


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--copy", required=True, type=Path)
    parser.add_argument("--audit", type=Path, help="path of the org-transfer-audit script; the built tree must be `ready`")
    parser.add_argument("--org", choices=sorted(ORGS), default=DEFAULT_ORG.prefix,
                        help="the organization the copy is for (B-115); default %(default)s")
    args = parser.parse_args(argv)
    build(args.ref, args.copy.resolve(), args.audit, org=ORGS[args.org])


if __name__ == "__main__":
    main()
