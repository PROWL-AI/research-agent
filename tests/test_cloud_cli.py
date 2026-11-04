"""Operator commands of the cloud instance (B-099 M1, M3)."""
import json

import pytest

from research_agent.service import cli


def run(argv, tmp_path):
    lines = []
    code = cli.client_command(argv, {"PROWL_RESEARCH_ROOT": str(tmp_path)}, lines.append)
    return code, lines


def test_client_add_prints_the_key_once_and_list_never(tmp_path):
    code, lines = run(["add", "anna", "--scopes", "read,tools.call"], tmp_path)
    assert code == 0
    key = lines[0].split(": ", 1)[1]
    assert key.startswith("prc_")
    _, listed = run(["list"], tmp_path)
    assert key not in listed[0]
    assert json.loads(listed[0])[0]["scopes"] == ["read", "tools.call"]
    _, lines = run(["revoke", "anna"], tmp_path)
    assert lines == ["revoked anna"]


def test_client_needs_a_name(tmp_path):
    with pytest.raises(SystemExit):
        run(["add"], tmp_path)


@pytest.mark.parametrize("env,message", [
    ({}, "PUBLIC_ORIGIN"),
    ({"PUBLIC_ORIGIN": "http://x.test"}, "PUBLIC_ORIGIN"),
    ({"PUBLIC_ORIGIN": "https://x.test/path"}, "PUBLIC_ORIGIN"),
    ({"PUBLIC_ORIGIN": "https://x.test", "FABRIC_SERVICE_TOKEN": "short"}, "FABRIC_SERVICE_TOKEN"),
])
def test_cloud_run_refuses_an_incomplete_configuration(env, message):
    with pytest.raises(SystemExit) as exc:
        cli.cloud_run(env)
    assert message in str(exc.value)
