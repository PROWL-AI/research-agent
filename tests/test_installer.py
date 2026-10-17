"""The launchd installer's vault-only launch (wave 5): argv shape and slot check, offline."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "install-fabric-service.py"


def _installer():
    spec = importlib.util.spec_from_file_location("install_fabric_service", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _engine(tmp_path):
    venv = tmp_path / "obs-venv"
    engine = venv / "lib" / "python3.14" / "site-packages" / "observatory" / "engine"
    engine.mkdir(parents=True)
    (venv / "bin").mkdir()
    (venv / "bin" / "python").write_text("")
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
    return venv, engine


def test_the_service_starts_under_the_vault_only_service_consumer(tmp_path, monkeypatch):
    inst = _installer()
    venv, engine = _engine(tmp_path)
    monkeypatch.setattr(inst, "command", lambda *args, **kw: str(engine))
    argv = inst.launch_argv("/py", tmp_path / "data", 18764, tmp_path / "build.json", tmp_path / "logs", "folder")
    assert argv[:9] == [str(venv / "bin" / "python"), str(engine / "tools/use_secret.py"), "serve", "--env", "prod",
                        "--consumer", inst.LABEL, "folder", "PROWL_API_KEY,RESEARCH_LLM_API_KEY"]
    assert argv[9] == "--" and argv[10:13] == ["/py", "-m", "research_agent.service.cli"]
    assert "run" not in argv[:9]  # `run` is for one-off commands; a service is `serve`


def test_slots_are_matched_by_exact_name(tmp_path, monkeypatch):
    inst = _installer()
    _, engine = _engine(tmp_path)
    listing = "  folder/prod/PROWL_API_KEY_OLD  (40B)\n  folder/local/RESEARCH_LLM_API_KEY  (40B)\n" \
              "  other/prod/RESEARCH_LLM_API_KEY  (40B)\n"
    monkeypatch.setattr(inst, "command", lambda *args, **kw: str(engine) if args[0] == "project-observatory" else listing)
    assert inst.missing_slots("folder") == ["PROWL_API_KEY", "RESEARCH_LLM_API_KEY"]
    listing = "  folder/prod/PROWL_API_KEY  (40B)\n  folder/prod/RESEARCH_LLM_API_KEY  (40B, rotated 2026-10-01×1)\n"
    assert inst.missing_slots("folder") == []


def test_without_a_vault_the_service_starts_with_no_keys(tmp_path):
    inst = _installer()
    argv = inst.launch_argv("/py", tmp_path / "data", 18764, tmp_path / "build.json", tmp_path / "logs", None)
    assert argv[0] == "/py" and "use_secret" not in " ".join(argv)
