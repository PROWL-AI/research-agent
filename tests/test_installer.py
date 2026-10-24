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


def test_a_folder_with_some_slots_launches_degraded_and_one_with_none_is_refused(tmp_path, monkeypatch):
    inst = _installer()
    _, engine = _engine(tmp_path)
    listing = {"v": "  folder/prod/RESEARCH_LLM_API_KEY  (73B)\n"}
    monkeypatch.setattr(inst, "command", lambda *a, **kw: str(engine) if a[0] == "project-observatory" else listing["v"])

    class P:
        def error(self, message):
            raise SystemExit(message)

    held, missing = inst.held_slots("folder", P())
    assert held == ["RESEARCH_LLM_API_KEY"] and missing == ["PROWL_API_KEY"]
    argv = inst.launch_argv("/py", tmp_path, 18764, tmp_path / "b.json", tmp_path / "l", "folder", held)
    assert argv[8] == "RESEARCH_LLM_API_KEY"  # only what the folder holds reaches use_secret
    listing["v"] = "  folder/local/PROWL_API_KEY  (40B)\n"
    try:
        inst.held_slots("folder", P())
    except SystemExit as exc:
        assert "holds none" in str(exc)
    else:
        raise AssertionError("a folder with no slot must be refused")


def test_a_dry_run_reports_a_folder_problem_instead_of_refusing(tmp_path, monkeypatch):
    inst = _installer()
    _, engine = _engine(tmp_path)
    monkeypatch.setattr(inst, "command", lambda *a, **kw: str(engine) if a[0] == "project-observatory" else "")
    held, missing, problem = inst.slot_check("folder")
    assert held == [] and missing == list(inst.SLOTS) and "holds none" in problem


def test_readiness_waits_on_a_wall_clock_deadline_not_a_count_of_tries(monkeypatch):
    """B-093: a loaded machine answered after the old 480 tries had run out; the wait is a deadline."""
    inst = _installer()
    now = [0.0]
    # More refusals than the old 480 tries, then the previous release, then the new one.
    answers = iter([OSError("refused")] * 500 + [{"service": {"build": {"commit": "old"}}}, {"service": {"build": {"commit": "abc"}}}])

    class Reply:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def urlopen(url, timeout):
        assert url == "http://127.0.0.1:1/.well-known/fabric-service" and timeout == 3
        now[0] += 0.5  # every try is slow under load
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return Reply(answer)

    monkeypatch.setattr(inst.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(inst.json, "load", lambda reply: reply.body)
    assert inst.wait_ready("http://127.0.0.1:1", "abc", 600, clock=lambda: now[0], sleep=lambda _: None) is True
    assert now[0] > 120  # past the old wait
    assert inst.READY_TIMEOUT_S == 600.0


def test_readiness_gives_up_at_the_deadline(monkeypatch):
    inst = _installer()
    now = [0.0]

    def urlopen(url, timeout):
        now[0] += 1.0
        raise OSError("refused")

    monkeypatch.setattr(inst.urllib.request, "urlopen", urlopen)
    assert inst.wait_ready("http://127.0.0.1:1", "abc", 5, clock=lambda: now[0], sleep=lambda _: None) is False
    assert now[0] <= 7


def test_build_output_in_the_archive_never_reaches_the_install(tmp_path):
    """0.3.0 and 0.3.1 carried a committed build/lib, which setuptools installed in place of the sources."""
    inst = _installer()
    source = tmp_path / "source"
    (source / "build" / "lib" / "research_agent").mkdir(parents=True)
    (source / "prowl_research_agent.egg-info").mkdir()
    (source / "research_agent").mkdir()
    assert sorted(inst.strip_build_output(source)) == ["build", "prowl_research_agent.egg-info"]
    assert not (source / "build").exists() and (source / "research_agent").is_dir()


def test_no_build_output_is_tracked():
    import subprocess

    root = SCRIPT.parent.parent
    tracked = subprocess.run(["git", "ls-files", "build", "*.egg-info"], cwd=root, capture_output=True, text=True, check=True)
    assert tracked.stdout == ""
