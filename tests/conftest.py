from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "evals" / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.plan_payload: dict[str, Any] = {"plan": []}
        self.claims_payload: dict[str, Any] = {"claims": []}
        self.report_text = "# Report\n\nNo numbers here."
        self.transform_text = "Transform synthesis notes."
        self.text_queue: list[str] = []
        self.fidelity_payload: dict[str, Any] = {"verdicts": []}

    async def __aenter__(self) -> "FakeLLM":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def complete(
        self,
        messages: list[dict[str, str]],
        tier: str = "cheap",
        json_mode: bool = False,
        **kwargs: Any,
    ) -> str:
        self.calls.append({"tier": tier, "json_mode": json_mode, "messages": messages})
        if tier == "strong" and json_mode:
            return json.dumps(self.plan_payload)
        if tier == "cheap" and json_mode:
            if "citation-fidelity" in messages[0]["content"]:
                return json.dumps(self.fidelity_payload)
            return json.dumps(self.claims_payload)
        if tier == "cheap":
            return self.transform_text
        if self.text_queue:
            return self.text_queue.pop(0)
        return self.report_text


class FakeProwl:
    def __init__(self, catalog: list[str] | None = None) -> None:
        self.catalog = catalog or ["spyfu_get_domain_stats", "dataforseo_bl_summary"]
        self.tool_calls: list[dict[str, Any]] = []
        self.call_log: list[Any] = []
        self.cost_usd: float | None = None
        self.tool_prices: dict[str, float | None] = {}
        self.list_tools_calls = 0
        self.cost_per_call: float | None = None
        self.fail_on: set[str] = set()

    @property
    def calls_made(self) -> int:
        return len(self.call_log)

    @property
    def data_calls(self) -> int:
        return len(self.tool_calls)

    async def __aenter__(self) -> "FakeProwl":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def list_tools(self) -> list[str]:
        self.list_tools_calls += 1
        return list(self.catalog)

    async def tool_info(self, name: str) -> dict[str, Any]:
        return {"name": name, "input_schema": {"type": "object", "properties": {}}}

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.tool_calls.append({"name": name, "arguments": arguments})
        self.call_log.append(object())
        if name in self.fail_on:
            from research_agent.prowl_client import ToolCallError

            raise ToolCallError(f"{name}: simulated failure")
        if self.cost_per_call is not None:
            self.cost_usd = (self.cost_usd or 0.0) + self.cost_per_call
        return {"tool": name, "rows": [{"value": 42}]}

    async def wallet(self) -> dict[str, float]:
        return {"balance_usd": 10.0}


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def fake_prowl() -> FakeProwl:
    return FakeProwl()


@pytest.fixture
def mini_runbooks_dir(tmp_path: Path) -> Path:
    runbook_dir = tmp_path / "runbooks" / "mini-teardown"
    runbook_dir.mkdir(parents=True)
    (runbook_dir / "SKILL.md").write_text(
        """\
---
name: mini-teardown
description: minimal test runbook
version: "1.0"
inputs:
  - { name: competitors, type: "list[domain]", required: true, max: 3 }
  - { name: market, type: "string", required: false }
tools:
  - spyfu_get_domain_stats
  - dataforseo_bl_summary
budget: { max_tool_calls: 2, max_usd: 1.00, max_minutes: 30 }
outputs: { report_template: test, formats: [markdown] }
---

# Mini Teardown

## Sequence

1. **Baseline** — `spyfu_get_domain_stats` per competitor.

## Verification (hard rules)

- none

## Output instructions

Template `test`. Required sections:

1. **Executive summary** — key findings, one line each.
2. **Source log** — every figure with tool + retrieval date.
""",
        encoding="utf-8",
    )
    usd_dir = tmp_path / "runbooks" / "mini-usd"
    usd_dir.mkdir(parents=True)
    (usd_dir / "SKILL.md").write_text(
        """\
---
name: mini-usd
description: minimal test runbook with a tight usd budget
version: "1.0"
inputs:
  - { name: competitors, type: "list[domain]", required: true, max: 3 }
tools:
  - spyfu_get_domain_stats
budget: { max_tool_calls: 10, max_usd: 0.50, max_minutes: 30 }
outputs: { report_template: test, formats: [markdown] }
---

# Mini USD

## Sequence

1. **Baseline** — `spyfu_get_domain_stats` per competitor.

## Verification (hard rules)

- none

## Output instructions

Template `test`. Required sections:

1. **Executive summary** — key findings, one line each.
""",
        encoding="utf-8",
    )
    return tmp_path / "runbooks"


@pytest.fixture
def patched_runbooks(monkeypatch, mini_runbooks_dir):
    monkeypatch.setattr("research_agent.runbook.RUNBOOKS_DIR", mini_runbooks_dir)
    return mini_runbooks_dir
