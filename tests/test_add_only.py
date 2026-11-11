"""B-105, rule R28: what shipped (runbooks at their version, report templates) is never changed or deleted."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("check_add_only", ROOT / "scripts" / "check_add_only.py")
check_add_only = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_add_only)

SKILL = """---
name: {name}
description: test runbook
version: "{version}"
---
{body}
"""


def _codes(found):
    return sorted((f["code"], f["name"]) for f in found)


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    for name in ("alpha", "beta"):
        d = tmp_path / "research_agent" / "runbooks" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(SKILL.format(name=name, version="1.0", body="steps"), encoding="utf-8")
    t = tmp_path / "research_agent" / "report" / "templates"
    t.mkdir(parents=True)
    (t / "base.html.j2").write_text("<html>{{ body }}</html>", encoding="utf-8")
    lock = check_add_only.add_only.lock(check_add_only.catalog(tmp_path))
    (tmp_path / "catalog").mkdir()
    (tmp_path / "catalog" / "shipped.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    return tmp_path


def test_the_repository_keeps_every_shipped_entry():
    """The gate itself: this tree carries every runbook version and template the lock names, unchanged."""
    assert check_add_only.findings(ROOT) == []


def test_the_lock_names_every_runbook_and_template_the_tree_offers():
    names = set(json.loads((ROOT / "catalog" / "shipped.lock.json").read_text())["names"])
    assert set(check_add_only.catalog(ROOT)["entries"]) <= names


def test_an_untouched_tree_passes(tree: Path):
    assert check_add_only.findings(tree) == []


def test_an_edited_runbook_without_a_new_version_is_refused(tree: Path):
    skill = tree / "research_agent" / "runbooks" / "alpha" / "SKILL.md"
    skill.write_text(SKILL.format(name="alpha", version="1.0", body="steps, quietly changed"), encoding="utf-8")
    assert _codes(check_add_only.findings(tree)) == [("changed", "runbook/alpha@1.0")]


def test_a_new_version_that_drops_the_shipped_text_is_refused(tree: Path):
    skill = tree / "research_agent" / "runbooks" / "alpha" / "SKILL.md"
    skill.write_text(SKILL.format(name="alpha", version="1.1", body="better steps"), encoding="utf-8")
    assert _codes(check_add_only.findings(tree)) == [("missing", "runbook/alpha@1.0")]


def test_a_new_version_beside_the_archived_shipped_text_passes(tree: Path):
    d = tree / "research_agent" / "runbooks" / "alpha"
    (d / "versions").mkdir()
    shutil.copyfile(d / "SKILL.md", d / "versions" / "1.0.md")
    (d / "SKILL.md").write_text(SKILL.format(name="alpha", version="1.1", body="better steps"), encoding="utf-8")
    assert check_add_only.findings(tree) == []
    new = check_add_only.add_only.lock(check_add_only.catalog(tree), json.loads(
        (tree / "catalog" / "shipped.lock.json").read_text()))
    assert {"runbook/alpha@1.0", "runbook/alpha@1.1"} <= set(new["names"])


def test_an_archived_version_that_was_edited_is_refused(tree: Path):
    d = tree / "research_agent" / "runbooks" / "alpha"
    (d / "versions").mkdir()
    (d / "versions" / "1.0.md").write_text("not what shipped", encoding="utf-8")
    (d / "SKILL.md").write_text(SKILL.format(name="alpha", version="1.1", body="better steps"), encoding="utf-8")
    assert _codes(check_add_only.findings(tree)) == [("changed", "runbook/alpha@1.0")]


def test_a_deleted_runbook_is_refused(tree: Path):
    shutil.rmtree(tree / "research_agent" / "runbooks" / "beta")
    assert _codes(check_add_only.findings(tree)) == [("missing", "runbook/beta@1.0")]


def test_an_edited_template_is_refused_and_a_new_one_is_added(tree: Path):
    t = tree / "research_agent" / "report" / "templates"
    (t / "base.html.j2").write_text("<html>restyled</html>", encoding="utf-8")
    assert _codes(check_add_only.findings(tree)) == [("changed", "template/base.html.j2")]
    (t / "base.html.j2").write_text("<html>{{ body }}</html>", encoding="utf-8")
    (t / "editorial.html.j2").write_text("<html>restyled</html>", encoding="utf-8")
    assert check_add_only.findings(tree) == []


def test_a_retirement_needs_a_date_and_a_reason_and_keeps_the_entry(tree: Path):
    retired = tree / "catalog" / "retired.json"
    retired.write_text(json.dumps({"runbook/beta@1.0": {"date": "2026-11-11"}}), encoding="utf-8")
    assert _codes(check_add_only.findings(tree)) == [("retired-incomplete", "runbook/beta@1.0")]
    retired.write_text(json.dumps({"runbook/beta@1.0": {"date": "2026-11-11", "reason": "superseded"}}),
                       encoding="utf-8")
    assert check_add_only.findings(tree) == []
    shutil.rmtree(tree / "research_agent" / "runbooks" / "beta")
    assert _codes(check_add_only.findings(tree)) == [("missing", "runbook/beta@1.0")]


def test_a_retirement_of_an_entry_that_never_shipped_is_refused(tree: Path):
    (tree / "catalog" / "retired.json").write_text(
        json.dumps({"runbook/gamma@1.0": {"date": "2026-11-11", "reason": "x"}}), encoding="utf-8")
    assert _codes(check_add_only.findings(tree)) == [("retired-unknown", "runbook/gamma@1.0")]


def test_a_missing_lock_is_refused(tree: Path):
    (tree / "catalog" / "shipped.lock.json").unlink()
    assert _codes(check_add_only.findings(tree)) == [("no-lock", "catalog/shipped.lock.json")]


def test_a_lock_rewritten_to_hide_a_deletion_is_refused(tree: Path):
    git = ["git", "-C", str(tree), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run(git[:3] + ["init", "-q"], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-qm", "base"], check=True)
    shutil.rmtree(tree / "research_agent" / "runbooks" / "beta")
    lock_path = tree / "catalog" / "shipped.lock.json"
    lock = json.loads(lock_path.read_text())
    del lock["names"]["runbook/beta@1.0"]
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    assert check_add_only.findings(tree) == []  # the deletion hides from a check that trusts the new lock
    assert _codes(check_add_only.findings(tree, base="HEAD")) == [("lock-rewritten", "runbook/beta@1.0")]


def test_an_unreadable_base_is_an_error_not_a_pass(tree: Path):
    with pytest.raises(ValueError):
        check_add_only.findings(tree, base="no-such-revision")


def test_a_runbook_without_a_version_is_an_error(tree: Path):
    (tree / "research_agent" / "runbooks" / "alpha" / "SKILL.md").write_text("---\nname: alpha\n---\n", encoding="utf-8")
    with pytest.raises(ValueError):
        check_add_only.catalog(tree)


def test_the_vendored_guard_is_the_database_pattern_unchanged():
    assert check_add_only.add_only.__version__ == "1.0.0"
