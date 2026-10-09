from typing import Any

import json

import pytest
from mcp.types import CallToolResult, TextContent

from research_agent.prowl_client import ProwlClient, ProwlError


class FakeRPCProwl(ProwlClient):
    def __init__(self, pages: list[Any]) -> None:
        super().__init__(api_key="test", mcp_url="http://unused.invalid")
        self.pages = pages
        self.rpc_calls: list[dict[str, Any]] = []

    async def _invoke(self, prowl_tool: str, arguments: dict[str, Any]) -> Any:
        self.rpc_calls.append({"tool": prowl_tool, "arguments": arguments})
        assert prowl_tool == "prowl_list_tools"
        return self.pages[len(self.rpc_calls) - 1]


def _page(names, next_offset, prices=None):
    return {
        "tools": names,
        "total": 3,
        "count": len(names),
        "limit": 200,
        "next_offset": next_offset,
        "prices": prices or {},
    }


async def test_list_tools_paginates_and_merges_prices():
    client = FakeRPCProwl(
        [
            _page(
                ["alpha_tool", "beta_tool"],
                next_offset=2,
                prices={
                    "alpha_tool": {"estimated_billed_usd": 0.01},
                    "beta_tool": {"estimated_billed_usd": None},
                },
            ),
            _page(
                ["gamma_tool"],
                next_offset=None,
                prices={"gamma_tool": {"estimated_billed_usd": 0.5}},
            ),
        ]
    )

    names = await client.list_tools()

    assert names == ["alpha_tool", "beta_tool", "gamma_tool"]
    assert [c["arguments"] for c in client.rpc_calls] == [
        {"names": True, "limit": 200, "offset": 0},
        {"names": True, "limit": 200, "offset": 2},
    ]
    assert client.tool_prices == {
        "alpha_tool": 0.01,
        "beta_tool": None,
        "gamma_tool": 0.5,
    }


async def test_list_tools_caches_after_first_fetch():
    client = FakeRPCProwl([_page(["only_tool"], next_offset=None)])
    first = await client.list_tools()
    second = await client.list_tools()
    assert first == second == ["only_tool"]
    assert len(client.rpc_calls) == 1


async def test_counts_payload_is_an_error_not_a_catalog():
    client = FakeRPCProwl(
        [{"categories": {"seo": 100}, "total_tools": 442, "hint": "Counts only."}]
    )
    with pytest.raises(ProwlError, match="names page"):
        await client.list_tools()


async def test_stalled_pagination_is_an_error():
    client = FakeRPCProwl(
        [
            _page(["a"], next_offset=1),
            _page(["b"], next_offset=1),
        ]
    )
    with pytest.raises(ProwlError, match="stalled"):
        await client.list_tools()


class FakeMCPProwl(ProwlClient):
    def __init__(self, payloads: list[Any]) -> None:
        super().__init__(api_key="test", mcp_url="http://unused.invalid")
        self.payloads = payloads
        self.rpc_calls: list[dict[str, Any]] = []

    async def _rpc(self, name: str, arguments: dict[str, Any] | None = None, *, retry: bool = True) -> CallToolResult:
        self.rpc_calls.append({"tool": name, "arguments": arguments})
        payload = self.payloads[len(self.rpc_calls) - 1]
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(payload))]
        )


async def test_tool_info_and_call_tool_send_server_arg_names():
    client = FakeMCPProwl([
        {"name": "foo_tool", "input_schema": {}},
        {"result": {"rows": []}},
    ])
    await client.tool_info("foo_tool")
    await client.call_tool("bar_tool", {"domain": "x.com"})

    assert client.rpc_calls[0] == {
        "tool": "prowl_tool_info",
        "arguments": {"tool_name": "foo_tool"},
    }
    assert client.rpc_calls[1] == {
        "tool": "prowl_call_tool",
        "arguments": {"tool_name": "bar_tool", "params": {"domain": "x.com"}},
    }


async def test_billing_block_accumulates_cost():
    payload = {
        "result": {"rows": [1]},
        "billing": {
            "estimated_cost_usd": 0.005,
            "actual_cost_usd": 0.0042,
            "provider_cost_usd": 0.003,
            "markup_usd": 0.0012,
            "debited": 0.0042,
            "cost_source": "fixed",
        },
    }
    client = FakeMCPProwl([payload, payload])
    await client.call_tool("spyfu_get_domain_stats", {"domain": "x.com"})
    await client.call_tool("spyfu_get_domain_stats", {"domain": "y.com"})

    assert client.cost_usd == pytest.approx(0.0084)
    assert client.call_log[-1].cost_usd == pytest.approx(0.0042)


async def test_no_billing_block_leaves_cost_unknown():
    client = FakeMCPProwl([{"result": {"rows": [1]}}])
    await client.call_tool("spyfu_get_domain_stats", {"domain": "x.com"})
    assert client.cost_usd is None
    assert client.call_log[-1].cost_usd is None


async def test_meta_cost_fallback_when_no_billing_block():
    class MetaProwl(FakeMCPProwl):
        async def _rpc(self, name, arguments=None, *, retry=True):
            self.rpc_calls.append({"tool": name, "arguments": arguments})
            return CallToolResult(
                content=[TextContent(type="text", text='{"result": {}}')],
                _meta={"cost_usd": 0.01},
            )

    client = MetaProwl([])
    await client.call_tool("spyfu_get_domain_stats", {})
    assert client.cost_usd == pytest.approx(0.01)


class StubSession:
    def __init__(self, result: CallToolResult | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = result or CallToolResult(
            content=[TextContent(type="text", text="{}")]
        )

    async def call_tool(self, name, arguments, read_timeout_seconds=None, **kwargs):
        self.calls.append({
            "name": name,
            "arguments": arguments,
            "read_timeout_seconds": read_timeout_seconds,
        })
        return self.result


class TestCallTimeout:
    async def test_default_read_timeout_is_passed(self):
        from datetime import timedelta

        client = ProwlClient(api_key="t", mcp_url="http://unused.invalid")
        client._session = StubSession()

        await client._rpc("prowl_get_wallet", {})

        assert client._session.calls[0]["read_timeout_seconds"] == timedelta(seconds=180)

    async def test_env_overrides_read_timeout(self, monkeypatch):
        from datetime import timedelta

        monkeypatch.setenv("RESEARCH_PROWL_CALL_TIMEOUT_S", "42")
        client = ProwlClient(api_key="t", mcp_url="http://unused.invalid")
        client._session = StubSession()

        await client._rpc("prowl_get_wallet", {})

        assert client._session.calls[0]["read_timeout_seconds"] == timedelta(seconds=42)

    async def test_invalid_env_falls_back_to_default(self, monkeypatch):
        from datetime import timedelta

        monkeypatch.setenv("RESEARCH_PROWL_CALL_TIMEOUT_S", "soon")
        client = ProwlClient(api_key="t", mcp_url="http://unused.invalid")
        client._session = StubSession()

        await client._rpc("prowl_get_wallet", {})

        assert client._session.calls[0]["read_timeout_seconds"] == timedelta(seconds=180)


class TestStreamClosureRetry:
    async def test_unmetered_call_retries_closed_stream(self, monkeypatch):
        from anyio import ClosedResourceError

        monkeypatch.setattr("research_agent.prowl_client._BACKOFF_BASE_S", 0)
        client = ProwlClient(api_key="t", mcp_url="http://unused.invalid")
        attempts = 0

        class FlakySession(StubSession):
            async def call_tool(self, *args, **kwargs):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise ClosedResourceError()
                return await super().call_tool(*args, **kwargs)

        async def fake_reconnect():
            client._session = FlakySession()

        monkeypatch.setattr(client, "_reconnect", fake_reconnect)
        client._session = FlakySession()

        result = await client._rpc("prowl_list_tools", {})

        assert result is not None
        assert attempts == 3

    async def test_billed_call_tool_is_never_retried_on_closed_stream(self):
        from anyio import ClosedResourceError

        client = ProwlClient(api_key="t", mcp_url="http://unused.invalid")
        attempts = 0

        class DeadSession(StubSession):
            async def call_tool(self, *args, **kwargs):
                nonlocal attempts
                attempts += 1
                raise ClosedResourceError()

        client._session = DeadSession()

        with pytest.raises(ProwlError, match="prowl_call_tool"):
            await client.call_tool("spyfu_get_domain_stats", {"domain": "x.com"})
        assert attempts == 1

    async def test_session_is_reread_after_reconnect(self, monkeypatch):
        client = ProwlClient(api_key="t", mcp_url="http://unused.invalid")
        client._session = None

        async def fake_reconnect():
            client._session = StubSession()

        monkeypatch.setattr(client, "_reconnect", fake_reconnect)

        result = await client._rpc("prowl_get_wallet", {})

        assert result is not None
        assert isinstance(client._session, StubSession)
        assert client._session.calls[0]["name"] == "prowl_get_wallet"
