"""Async MCP client for the remote Prowl server (streamable HTTP)."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError
from mcp.types import CallToolResult, TextContent

log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_BACKOFF_BASE_S = 1.0
#: The catalog is ~450 names at 200/page; 50 pages is ten times that — a
#: server regression grows offsets forever otherwise, and the page is a
#: network call each iteration.
_MAX_CATALOG_PAGES = 50

COST_META_KEYS = ("cost_usd", "cost", "price_usd", "price")


class ProwlError(Exception):
    pass


class ToolCallError(ProwlError):
    pass


@dataclass
class ToolCallRecord:
    tool: str
    arguments: dict[str, Any]
    ok: bool
    at: str
    error: str | None = None
    cost_usd: float | None = None


@dataclass
class ProwlClient:
    api_key: str
    mcp_url: str
    call_log: list[ToolCallRecord] = field(default_factory=list)
    cost_usd: float | None = None
    tool_prices: dict[str, float | None] = field(default_factory=dict)

    _stack: AsyncExitStack | None = field(default=None, init=False, repr=False)
    _session: ClientSession | None = field(default=None, init=False, repr=False)
    _catalog_cache: list[str] | None = field(default=None, init=False, repr=False)
    _tool_info_cache: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _connect_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, init=False, repr=False
    )

    @property
    def calls_made(self) -> int:
        return len(self.call_log)

    async def __aenter__(self) -> "ProwlClient":
        self._stack = AsyncExitStack()
        await self._connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._session = None
        self._stack = None

    async def _connect(self) -> None:
        assert self._stack is not None
        read, write, _ = await self._stack.enter_async_context(
            streamablehttp_client(
                self.mcp_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        )
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._session = session

    async def _reconnect(self) -> None:
        # Parallel workers share this client: two workers hitting a transport
        # error at the same moment must not each tear down the other's fresh
        # stack mid-flight — reconnects are serialized. Two queued reconnects
        # in a row are harmless: callers re-read ``self._session`` afterwards.
        async with self._connect_lock:
            await self.aclose()
            self._stack = AsyncExitStack()
            await self._connect()

    async def _rpc(
        self, name: str, arguments: dict[str, Any] | None = None, *, retry: bool = True
    ) -> CallToolResult:
        attempts = _MAX_ATTEMPTS if retry else 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                if self._session is None:
                    await self._reconnect()
                assert self._session is not None
                return await self._session.call_tool(name, arguments or {})
            except McpError:
                raise
            except (httpx.HTTPError, ConnectionError, TimeoutError, OSError) as exc:
                last_error = exc
                log.warning(
                    "prowl RPC %s failed (attempt %d/%d): %s",
                    name, attempt, attempts, exc,
                )
                if attempt < attempts:
                    await asyncio.sleep(_BACKOFF_BASE_S * attempt)
                    try:
                        await self._reconnect()
                    except Exception as reconnect_exc:
                        log.warning("prowl reconnect failed: %s", reconnect_exc)
        raise ProwlError(
            f"prowl RPC '{name}' failed after {attempts} attempts: {last_error}"
        )

    async def _invoke(self, prowl_tool: str, arguments: dict[str, Any]) -> Any:
        record = ToolCallRecord(
            tool=prowl_tool,
            arguments=arguments,
            ok=False,
            at=datetime.now(timezone.utc).isoformat(),
        )
        self.call_log.append(record)
        # NEVER retry the billed data plane: the server debits the wallet per
        # dispatch, so a timed-out-but-executed call retried by the client is
        # paid for twice. Meta calls (catalog, search, wallet) are unmetered
        # and retry normally.
        retry = prowl_tool != "prowl_call_tool"
        try:
            result = await self._rpc(prowl_tool, arguments, retry=retry)
        except McpError as exc:
            record.error = f"JSON-RPC {exc.error.code}: {exc.error.message}"
            raise ToolCallError(f"{prowl_tool}: {record.error}") from exc
        except ProwlError as exc:
            record.error = str(exc)
            raise

        payload = _parse_content(result)
        record.cost_usd = _extract_billing_cost(prowl_tool, payload)
        if record.cost_usd is None:
            record.cost_usd = _extract_cost(result)
        if record.cost_usd is not None:
            self.cost_usd = (self.cost_usd or 0.0) + record.cost_usd

        if result.isError:
            record.error = _content_text(result)
            raise ToolCallError(f"{prowl_tool}: tool returned error: {record.error[:300]}")

        record.ok = True
        return payload

    async def search_tools(self, query: str) -> Any:
        return await self._invoke("prowl_search_tools", {"query": query})

    async def list_tools(self) -> list[str]:
        if self._catalog_cache is None:
            names: list[str] = []
            prices: dict[str, float | None] = {}
            offset = 0
            for _page in range(_MAX_CATALOG_PAGES):
                payload = await self._invoke(
                    "prowl_list_tools",
                    {"names": True, "limit": 200, "offset": offset},
                )
                page_names, next_offset, page_prices = _parse_names_page(payload)
                names.extend(page_names)
                prices.update(page_prices)
                if next_offset is None:
                    break
                if next_offset <= offset:
                    raise ProwlError(
                        "prowl_list_tools pagination stalled: "
                        f"next_offset={next_offset} <= offset={offset}"
                    )
                offset = next_offset
            else:
                raise ProwlError(
                    f"prowl_list_tools pagination exceeded {_MAX_CATALOG_PAGES} pages"
                )
            self._catalog_cache = names
            self.tool_prices = prices
        return list(self._catalog_cache)

    async def tool_info(self, name: str) -> Any:
        if name not in self._tool_info_cache:
            self._tool_info_cache[name] = await self._invoke(
                "prowl_tool_info", {"tool_name": name}
            )
        return self._tool_info_cache[name]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return await self._invoke(
            "prowl_call_tool", {"tool_name": name, "params": arguments}
        )

    async def wallet(self) -> Any:
        return await self._invoke("prowl_get_wallet", {})


def _content_text(result: CallToolResult) -> str:
    parts = [block.text for block in result.content if isinstance(block, TextContent)]
    return "\n".join(parts)


def _parse_content(result: CallToolResult) -> Any:
    if result.structuredContent is not None:
        content = result.structuredContent
        if isinstance(content, dict) and set(content) == {"result"}:
            inner = content["result"]
            if isinstance(inner, str):
                try:
                    return json.loads(inner)
                except json.JSONDecodeError:
                    return inner
            return inner
        return content
    text = _content_text(result)
    if not text:
        return result.model_dump(mode="json")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _extract_billing_cost(prowl_tool: str, payload: Any) -> float | None:
    if prowl_tool != "prowl_call_tool" or not isinstance(payload, dict):
        return None
    billing = payload.get("billing")
    if not isinstance(billing, dict):
        return None
    value = billing.get("actual_cost_usd")
    return float(value) if isinstance(value, (int, float)) else None


def _extract_cost(result: CallToolResult) -> float | None:
    meta = result.meta
    if not isinstance(meta, dict):
        return None
    for key in COST_META_KEYS:
        value = meta.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _parse_names_page(
    payload: Any,
) -> tuple[list[str], int | None, dict[str, float | None]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("tools"), list):
        shape = (
            ", ".join(sorted(payload.keys()))
            if isinstance(payload, dict)
            else type(payload).__name__
        )
        raise ProwlError(
            "unexpected prowl_list_tools payload: expected a names page with a "
            f"'tools' list (call with names=true); got keys: {shape}"
        )
    names = [str(name) for name in payload["tools"]]
    next_offset = payload.get("next_offset")
    if next_offset is not None and not isinstance(next_offset, int):
        raise ProwlError(
            f"prowl_list_tools page has non-integer next_offset: {next_offset!r}"
        )
    prices: dict[str, float | None] = {}
    raw_prices = payload.get("prices")
    if isinstance(raw_prices, dict):
        for name, row in raw_prices.items():
            if not isinstance(row, dict):
                continue
            value = row.get("estimated_billed_usd")
            prices[str(name)] = float(value) if isinstance(value, (int, float)) else None
    return names, next_offset, prices
