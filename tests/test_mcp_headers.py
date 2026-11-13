"""B-106: the headers helper reads the agent token only from a private file of this account."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "mcp_headers.py"


def _helper():
    spec = importlib.util.spec_from_file_location("mcp_headers", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _token(root: Path, mode: int = 0o600, text: str = "t" * 40) -> Path:
    path = root / "agent.token"
    path.write_text(text + "\n")
    path.chmod(mode)
    return path


def test_a_private_token_becomes_the_bearer_header(tmp_path, capsys):
    helper = _helper()
    _token(tmp_path)
    assert helper.main(["x", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"Authorization": "Bearer " + "t" * 40}


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644])
def test_a_token_others_can_read_is_refused(tmp_path, capsys, mode):
    helper = _helper()
    _token(tmp_path, mode)
    assert helper.main(["x", str(tmp_path)]) == 1
    out = capsys.readouterr()
    assert out.out == "" and "t" * 40 not in out.err


def test_a_missing_or_empty_token_prints_nothing(tmp_path, capsys):
    helper = _helper()
    assert helper.main(["x", str(tmp_path)]) == 1
    _token(tmp_path, text="")
    assert helper.main(["x", str(tmp_path)]) == 1
    assert capsys.readouterr().out == ""


def test_a_link_is_not_followed(tmp_path, capsys):
    helper = _helper()
    real = tmp_path / "real"
    real.mkdir()
    _token(real)
    (tmp_path / "agent.token").symlink_to(real / "agent.token")
    assert helper.main(["x", str(tmp_path)]) == 1
