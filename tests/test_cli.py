import sys

from research_agent.__main__ import main


def test_list_runbooks_without_env_keys(monkeypatch, capsys):
    monkeypatch.delenv("PROWL_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_LLM_API_KEY", raising=False)
    assert main(["list-runbooks"]) == 0
    out = capsys.readouterr().out
    assert "saas-competitor-teardown" in out
    assert "90 calls" in out


def test_mcp_stub_exits_zero(capsys):
    assert main(["mcp"]) == 0
    assert "phase 3" in capsys.readouterr().out


def test_validate_offline_via_cli():
    assert main(["validate"]) == 0


def test_run_requires_keys(monkeypatch, capsys):
    monkeypatch.delenv("PROWL_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_LLM_API_KEY", raising=False)
    assert main(["run", "saas-competitor-teardown", "--competitors", "a.com"]) == 1
    assert "PROWL_API_KEY" in capsys.readouterr().err
