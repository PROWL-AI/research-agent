"""B-047: the dashboard names who started a job — verified delegation, the
operator's panel, a declared requester, the service token — and the chain an
operator continuation belongs to. The label functions of app.js run under node."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "research_agent" / "service" / "static" / "app.js"


def _labels(jobs: list[dict]) -> list[list[str]]:
    source = APP.read_text(encoding="utf-8")
    pieces = [re.search(r"^const esc = .*$", source, re.M).group(0)]
    for name in ("who", "attribution"):
        start = source.index(f"const {name} = j =>")
        end = source.index(";\n", start) + 1
        pieces.append(source[start:end])
    script = "\n".join(pieces) + f"\nconsole.log(JSON.stringify({json.dumps(jobs)}.map(j => [who(j), attribution(j)])));"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_initiator_and_chain_labels():
    base = {"request": {"context": {}}}
    owner = {"principal": "urn:person:a", "caller": "caller-a.default"}
    rows = _labels([
        dict(base, delegation=dict(owner, tier="T2", kid="k1"), via="mcp"),
        dict(base, delegation=None, via="dashboard"),
        dict(base, delegation=None, via="mcp", chainOwner=owner),
        dict(base, delegation=None, via="dashboard", chainOwner=owner),
        {"request": {"context": {"requester": "Some agent"}}, "delegation": None, "via": "mcp"},
        dict(base, delegation=None, via="mcp"),
    ])
    who = [r[0] for r in rows]
    assert who[0].startswith("urn:person:a") and "через caller-a.default" in who[0]
    assert who[1] == "Оператор (панель)"
    assert who[2].startswith("Агент с токеном сервиса") and "продолжает цепочку urn:person:a" in who[2]
    assert who[3].startswith("Оператор (панель)") and "продолжает цепочку urn:person:a" in who[3]
    assert "(заявлено)" in who[4]
    assert who[5] == "Агент с токеном сервиса"
    assert rows[0][1].startswith("Проверено по токену делегирования (T2, ключ k1)")
    assert "не проверен" in rows[2][1]  # an operator continuation claims no token
