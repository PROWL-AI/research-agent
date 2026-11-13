"""The team copy is built from a named commit only (B-099 M7, D15 S2, S3, REQ-10)."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("build_team_copy", Path(__file__).resolve().parents[1] / "scripts" / "build_team_copy.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def sh(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def original(tmp_path):
    repo = tmp_path / "original"
    repo.mkdir()
    sh(repo, "init", "-q", "-b", "main")
    (repo / "LICENSE").write_text("MIT License\n")
    (repo / "research_agent").mkdir()
    (repo / "research_agent" / "x.py").write_text("x = 1\n")
    (repo / "docs" / "evidence").mkdir(parents=True)
    (repo / "docs" / "evidence" / "run.md").write_text("private run\n")
    (repo / "docs" / "HANDOFF.md").write_text("log\n")
    (repo / "docs" / "CLOUD.md").write_text("cloud\n")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-qm", "one")
    return repo


@pytest.fixture
def copy(tmp_path):
    repo = tmp_path / "copy"
    repo.mkdir()
    sh(repo, "init", "-q", "-b", "main")
    sh(repo, "commit", "-q", "--allow-empty", "-m", "init")
    return repo


def build(original, copy):
    return builder.build("HEAD", copy, out=lambda *_: None, root=original)


def test_build_writes_the_tree_without_what_stays_home(original, copy):
    build(original, copy)
    assert (copy / "research_agent" / "x.py").read_text() == "x = 1\n"
    assert (copy / "docs" / "CLOUD.md").exists()
    assert not (copy / "docs" / "evidence").exists() and not (copy / "docs" / "HANDOFF.md").exists()
    assert (copy / "LICENSE").read_bytes() == (original / "LICENSE").read_bytes()
    upstream = json.loads((copy / ".copy" / "upstream.json").read_text())
    head = sh(original, "rev-parse", "HEAD")
    assert upstream["sourceRevision"] == head and upstream["kind"] == "export"
    body = sh(copy, "log", "-1", "--format=%ae%n%B")
    assert body.startswith(builder.AUTHOR[1]) and f"Source-Revision: prowl-research@{head}" in body
    assert sh(copy, "branch", "--show-current") == f"sync/{head[:12]}"


def test_an_unported_copy_edit_refuses_the_next_build(original, copy):
    build(original, copy)
    (copy / "research_agent" / "x.py").write_text("x = 2\n")
    sh(copy, "commit", "-qam", "team edit")
    edit = sh(copy, "rev-parse", "HEAD")
    (original / "research_agent" / "y.py").write_text("y = 1\n")
    sh(original, "add", "-A")
    sh(original, "commit", "-qm", "two")
    with pytest.raises(SystemExit) as exc:
        build(original, copy)
    assert edit[:12] in str(exc.value)
    # Ported back: the original names the copy commit, and the build goes on.
    (original / "research_agent" / "x.py").write_text("x = 2\n")
    sh(original, "commit", "-qam", f"port the team edit\n\nBackports: {edit[:12]}")
    build(original, copy)
    upstream = json.loads((copy / ".copy" / "upstream.json").read_text())
    assert upstream["previousRevision"] is not None
    assert "(2 commits)" in sh(copy, "log", "-1", "--format=%s")


def test_a_commit_without_licence_is_refused(original, copy):
    sh(original, "rm", "-q", "LICENSE")
    sh(original, "commit", "-qm", "no licence")
    with pytest.raises(SystemExit):
        build(original, copy)


def test_an_audit_other_than_ready_refuses(original, copy, tmp_path):
    audit = tmp_path / "audit.py"
    audit.write_text('import json; print(json.dumps({"verdict": "fix_tree"}))\n')
    with pytest.raises(SystemExit) as exc:
        builder.build("HEAD", copy, audit, out=lambda *_: None, root=original)
    assert "fix_tree" in str(exc.value)
    audit.write_text('import json; print(json.dumps({"verdict": "ready"}))\n')
    builder.build("HEAD", copy, audit, out=lambda *_: None, root=original)


def test_an_empty_copy_repository_takes_the_first_build(original, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    sh(empty, "init", "-q", "-b", "main")
    builder.build("HEAD", empty, out=lambda *_: None, root=original)
    assert (empty / ".copy" / "upstream.json").exists()


def test_the_copy_carries_the_appvillis_prefix(original, copy):
    (original / "research_agent" / "service").mkdir(parents=True)
    (original / "research_agent" / "service" / "identity.py").write_text('SERVICE_ID = "prowl-research"\n')
    (original / "README.md").write_text("# Prowl Research Agent\n\nrun `prowl-research run`\n")
    (original / "docs" / "TEAM-ONBOARDING.md").write_text(
        "claude mcp add --transport http prowl-research https://x/mcp\nprowl-research-service client add\nprowl-research.cloud\n")
    sh(original, "add", "-A")
    sh(original, "commit", "-qm", "identity")
    build(original, copy)
    identity = (copy / "research_agent" / "service" / "identity.py").read_text()
    assert 'SERVICE_ID = "appvillis-prowl-research"' in identity and 'SERVICE_NAME = "Appvillis Prowl Research"' in identity
    assert (copy / "README.md").read_text().startswith("# Appvillis Prowl Research: Prowl Research Agent")
    assert "`prowl-research run`" in (copy / "README.md").read_text()
    onboarding = (copy / "docs" / "TEAM-ONBOARDING.md").read_text()
    assert "http appvillis-prowl-research https" in onboarding and "appvillis-prowl-research.cloud" in onboarding
    assert "prowl-research-service client add" in onboarding
    # The original keeps no prefix.
    assert 'SERVICE_ID = "prowl-research"' in (original / "research_agent" / "service" / "identity.py").read_text()


def test_a_passioncode_copy_carries_its_own_prefix_name_and_builder(original, copy):
    """B-115: `--org passioncode` builds the PassionCode copy with its own identity."""
    (original / "research_agent" / "service").mkdir(parents=True)
    (original / "research_agent" / "service" / "identity.py").write_text('SERVICE_ID = "prowl-research"\n')
    (original / "README.md").write_text("# Prowl Research Agent\n")
    sh(original, "add", "-A")
    sh(original, "commit", "-qm", "identity")
    org = builder.ORGS["passioncode"]
    builder.build("HEAD", copy, out=lambda *_: None, root=original, org=org)
    identity = (copy / "research_agent" / "service" / "identity.py").read_text()
    assert 'SERVICE_ID = "passioncode-prowl-research"' in identity and 'SERVICE_NAME = "PassionCode Prowl Research"' in identity
    assert (copy / "README.md").read_text().startswith("# PassionCode Prowl Research: ")
    assert sh(copy, "log", "-1", "--format=%ae") == "passioncode-prowl-research@users.noreply.github.com"
    # The next build finds the last one by this organization's builder, not Appvillis's.
    assert builder.last_build(copy, org)[0] is not None and builder.last_build(copy)[0] is None


def test_an_unknown_organization_is_refused():
    with pytest.raises(SystemExit):
        builder.main(["--ref", "HEAD", "--copy", ".", "--org", "nobody"])
