"""The launchd installer's vault-only launch (wave 5): argv shape and slot check, offline."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

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
    if not (root / ".git").exists():
        # The cloud deploy gate runs the suite in an extracted `git archive` (scripts/cloud.py `gate`), which has no
        # index: what is tracked is answered by the repository's own run of this test (B-116).
        pytest.skip("not a git checkout")
    tracked = subprocess.run(["git", "ls-files", "build", "*.egg-info"], cwd=root, capture_output=True, text=True, check=True)
    assert tracked.stdout == ""


# ── B-106: a space of a shared Mac with no GUI login ─────────────────────────────────────────────────────────────────


def test_a_space_daemon_has_its_own_label_home_path_and_no_stdout_file(tmp_path):
    inst = _installer()
    payload = {"Label": inst.LABEL, "ProgramArguments": ["/py"], "StandardOutPath": "/x", "StandardErrorPath": "/x",
               "EnvironmentVariables": {"PATH": "/usr/bin:/bin", "FABRIC_SERVICE_SUPERVISOR": "launchd"}}
    doc = inst.background_definition(payload, inst.background_label("passioncode"), tmp_path)
    assert doc["Label"] == "chat.prowl.research.passioncode"  # one /Library/LaunchDaemons for every space
    assert "StandardOutPath" not in doc and "StandardErrorPath" not in doc
    env = doc["EnvironmentVariables"]
    assert env["HOME"] == str(tmp_path) and env["OBSERVATORY_VAULT_ONLY"] == "1"
    assert env["PATH"].startswith("/opt/homebrew/bin:") and env["PATH"].endswith(f"{tmp_path}/.local/bin")
    assert env["FABRIC_SERVICE_SUPERVISOR"] == "launchd"
    assert payload["Label"] == inst.LABEL  # the caller's payload is not changed


def test_the_first_apply_line_names_the_account_and_the_label():
    inst = _installer()
    line = inst.first_apply_line("sshlg", "chat.prowl.research.sshlg")
    assert line == ("sudo /usr/bin/python3 -I /usr/local/libexec/observatory-space-daemons apply "
                    "--user sshlg --label chat.prowl.research.sshlg")


class _Run:
    def __init__(self, code, out=""):
        self.code, self.out, self.argv = code, out, None

    def __call__(self, argv, **kw):
        import subprocess

        self.argv = argv
        return subprocess.CompletedProcess(argv, self.code, self.out, "")


@pytest.mark.parametrize("code, outcome", [(0, "loaded"), (3, "first-apply")])
def test_the_space_door_loads_a_changed_definition_or_asks_for_the_first_apply(code, outcome):
    inst = _installer()
    run = _Run(code, "done")
    assert inst.door_deploy("chat.prowl.research.sshlg", run=run) == (outcome, "done")
    assert run.argv == ["sudo", "-n", "/usr/local/libexec/studio-space-service", "deploy", "chat.prowl.research.sshlg"]


@pytest.mark.parametrize("code", [2, 4, 5])
def test_a_refusal_of_the_space_door_stops_the_install(code):
    inst = _installer()
    with pytest.raises(RuntimeError, match=f"exit {code}"):
        inst.door_deploy("chat.prowl.research.sshlg", run=_Run(code, "plan-refused: x"))


def test_a_port_another_listener_holds_is_seen():
    import socket

    inst = _installer()
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        assert inst.port_answers(port) is True
    assert inst.port_answers(port) is False
