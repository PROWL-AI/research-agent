"""Operator scripts of the cloud instance (B-099 M5, M6): deploy only a tested tree,
config vars by name only, a valid remote descriptor."""
import io
import json
import subprocess
import tarfile

import httpx
import pytest

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("cloud_ops", Path(__file__).resolve().parents[1] / "scripts" / "cloud.py")
cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloud)


def tarball():
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("README.md")
        info.size = 2
        tar.addfile(info, io.BytesIO(b"hi"))
    return buffer.getvalue()


def test_a_red_suite_refuses_the_deploy():
    red = lambda *a, **k: subprocess.CompletedProcess(a, 1, "1 failed\n", "")  # noqa: E731
    with pytest.raises(SystemExit) as exc:
        cloud.gate(tarball(), red)
    assert "refused" in str(exc.value)
    green = lambda *a, **k: subprocess.CompletedProcess(a, 0, "1 passed\n", "")  # noqa: E731
    cloud.gate(tarball(), green)


def test_config_sends_only_named_known_variables_and_prints_names():
    sent, lines = [], []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    env = {"PROWL_API_KEY": "secret-1", "OPENROUTER_API_KEY": "secret-2", "HOME": "/x"}
    cloud.config("app", ["PROWL_API_KEY", "OPENROUTER_API_KEY"], client, env, lines.append)
    assert sent == [{"PROWL_API_KEY": "secret-1", "OPENROUTER_API_KEY": "secret-2"}]
    assert lines == ["set: OPENROUTER_API_KEY, PROWL_API_KEY"] and "secret" not in lines[0]
    with pytest.raises(SystemExit):
        cloud.config("app", ["HOME"], client, env, lines.append)
    with pytest.raises(SystemExit):
        cloud.config("app", ["RESEARCH_LLM_API_KEY"], client, env, lines.append)


def test_headers_need_the_key_in_the_environment():
    with pytest.raises(SystemExit):
        cloud.headers({})
    assert cloud.headers({"HEROKU_API_KEY": "k"})["Authorization"] == "Bearer k"


@pytest.mark.parametrize("origin", ["http://a.example.com", "https://a.example.com/x", "https://localhost", "https://u@a.example.com"])
def test_descriptor_refuses_a_bad_origin(origin, tmp_path):
    with pytest.raises(SystemExit):
        cloud.descriptor(origin, tmp_path / "t")


def test_register_writes_a_remote_descriptor(tmp_path):
    token = tmp_path / "token"
    token.write_text("x" * 40)
    token.chmod(0o644)
    with pytest.raises(SystemExit):
        cloud.register("https://research.example.com", token, tmp_path / "services", print)
    token.chmod(0o600)
    path = cloud.register("https://research.example.com", token, tmp_path / "services", lambda *_: None)
    data = json.loads(path.read_text())
    from research_agent.service.identity import SERVICE_ID
    assert path.name == f"{SERVICE_ID}.cloud.json" and data["id"] == SERVICE_ID
    assert data["placement"] == "remote" and data["instance"] == "cloud" and data["lifecycle"] == {"manager": "none"}
    assert data["origin"] == "https://research.example.com" and "commands" not in data
    assert data["peer"]["custody"] == "organization-managed"
    assert data["peer"]["residency"] == ["IE"] and data["peer"]["maxDataClass"] == "internal"
    assert data["runner"] == {"credentialKind": "key"}
