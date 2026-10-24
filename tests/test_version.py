"""One version: research_agent.__version__ is read by the package metadata, the well-known
document and MCP initialize, so a release bumps one line (0.3.0 found four copies, two disagreeing)."""

import re
import tomllib
from pathlib import Path

import research_agent
from research_agent.service import app, protocol

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_reads_the_package_version():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "version" not in project["project"] and "version" in project["project"]["dynamic"]
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "research_agent.__version__"}


def test_no_service_module_carries_its_own_version_literal():
    assert re.fullmatch(r"\d+\.\d+\.\d+", research_agent.__version__)
    for module in (app, protocol):
        source = Path(module.__file__).read_text()
        assert '"version": __version__' in source
        assert not re.search(r'"version": "\d+\.\d+\.\d+"', source), module.__name__
