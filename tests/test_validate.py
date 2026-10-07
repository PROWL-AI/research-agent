import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import validate_runbooks

from conftest import load_fixture


def test_offline_validation_passes(capsys):
    assert validate_runbooks.main(["--offline"]) == 0
    out = capsys.readouterr().out
    assert "all runbooks valid" in out


def test_snapshot_covers_flagship_allowlist():
    snapshot = json.loads(
        (Path(validate_runbooks.CATALOG_SNAPSHOT)).read_text(encoding="utf-8")
    )
    catalog = set(snapshot["tools"])
    from research_agent.runbook import get_runbook

    flagship = get_runbook("saas-competitor-teardown")
    assert set(flagship.meta.tools) <= catalog
    assert len(catalog) >= 40


def test_t1_nonexistent_tool_detected():
    fixture = load_fixture("t1_nonexistent_tool.json")
    catalog = ["spyfu_get_domain_stats", "dataforseo_bl_summary"]
    unknown = validate_runbooks.check_tools_against_catalog(
        fixture["runbook_fragment"]["tools"], catalog
    )
    assert unknown == fixture["expect"]["unknown_tools"]
