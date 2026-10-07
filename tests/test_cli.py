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


def test_mcp_subcommand_invokes_serve(monkeypatch):
    called = []
    monkeypatch.setattr("research_agent.mcp_server.serve", lambda: called.append(True))
    assert main(["mcp"]) == 0
    assert called == [True]


def test_validate_offline_via_cli():
    assert main(["validate"]) == 0


def test_run_requires_keys(monkeypatch, capsys):
    monkeypatch.delenv("PROWL_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_LLM_API_KEY", raising=False)
    assert main(["run", "saas-competitor-teardown", "--competitors", "a.com"]) == 1
    assert "PROWL_API_KEY" in capsys.readouterr().err


def test_rewrite_cli_round_trip(
    monkeypatch, capsys, tmp_path, mini_runbooks_dir, fake_llm
):
    import json as _json

    from research_agent.evidence.ledger import Ledger
    from research_agent.evidence.store import ArtifactStore, Checkpoint

    monkeypatch.setattr("research_agent.runbook.RUNBOOKS_DIR", mini_runbooks_dir)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RESEARCH_LLM_API_KEY", "test-key")
    monkeypatch.delenv("PROWL_API_KEY", raising=False)

    store = ArtifactStore(tmp_path / "runs" / "rw1")
    store.save_checkpoint(
        Checkpoint(
            run_id="rw1",
            runbook="mini-teardown",
            brief={"competitors": ["a.com"]},
        )
    )
    ledger = Ledger(tmp_path / "runs" / "rw1" / "ledger.json")
    ledger.add(
        claim="a.com traffic is 150,000",
        subject="a.com monthly organic traffic",
        value=150000,
        unit="visits/month",
        source_tool="spyfu_get_domain_stats",
    )
    ledger.save()
    (tmp_path / "runs" / "rw1" / "report.md").write_text("old draft\n")

    fake_llm.text_queue = [
        "The rival gets 150,000 monthly visitors.",
        "The rival gets 150,000 monthly visitors [C1] (ASSUMED, ±40%).",
    ]
    monkeypatch.setattr(
        "research_agent.llm.LLMClient", lambda **kwargs: fake_llm
    )

    assert main(["rewrite", "rw1"]) == 0
    out = capsys.readouterr().out
    assert "lint 1 -> 0" in out

    report = (tmp_path / "runs" / "rw1" / "report.md").read_text()
    assert "[C1]" in report

    checkpoint = _json.loads((tmp_path / "runs" / "rw1" / "checkpoint.json").read_text())
    assert checkpoint["stats"]["lint_issues_before"] == 1
    assert checkpoint["stats"]["lint_issues_after"] == 0


def test_rewrite_cli_errors_on_unknown_run(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RESEARCH_LLM_API_KEY", "test-key")
    monkeypatch.delenv("PROWL_API_KEY", raising=False)
    assert main(["rewrite", "nope"]) == 1
    assert "no checkpoint" in capsys.readouterr().err
