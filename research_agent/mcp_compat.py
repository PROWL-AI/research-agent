"""The MCP SDK, one import for its first and second major versions (B-112).

SDK 2 renamed the error (`McpError` became `MCPError`), replaced `streamablehttp_client(url, headers=...)` yielding
three streams with `streamable_http_client(url, http_client=httpx2.AsyncClient(...))` yielding two, took call
timeouts as seconds instead of a timedelta, moved its HTTP layer to `httpx2`, and renamed `FastMCP` to `MCPServer`.
The package pins SDK 2 (prowl.chat speaks protocol 2026-07-28 and will drop the old handshake); SDK 1 keeps working
for an environment that still has it.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, AsyncIterator

try:  # SDK 2
    import httpx2
    from mcp.client.streamable_http import streamable_http_client
    from mcp.server import MCPServer as Server
    from mcp.shared.exceptions import MCPError as McpError

    SDK = 2
    HTTP_ERRORS: tuple[type[BaseException], ...] = (httpx2.HTTPError,)
except ImportError:  # SDK 1
    from mcp.client.streamable_http import streamablehttp_client
    from mcp.server.fastmcp import FastMCP as Server  # noqa: F401  (re-exported)
    from mcp.shared.exceptions import McpError  # noqa: F401  (re-exported)

    SDK = 1
    HTTP_ERRORS = ()

#: The read deadline of a long tool call: Prowl's research and SERP tools can take minutes.
CONNECT_TIMEOUT_S = 30.0
READ_TIMEOUT_S = 300.0


@asynccontextmanager
async def open_streams(url: str, headers: dict[str, str]) -> AsyncIterator[tuple[Any, Any]]:
    """(read, write) streams of a streamable HTTP connection, whichever SDK is installed."""
    if SDK == 2:
        async with httpx2.AsyncClient(headers=headers, timeout=httpx2.Timeout(CONNECT_TIMEOUT_S, read=READ_TIMEOUT_S)) as http:
            async with streamable_http_client(url, http_client=http) as streams:
                yield streams[0], streams[1]
    else:
        async with streamablehttp_client(url, headers=headers) as streams:
            yield streams[0], streams[1]


def call_timeout(value: timedelta) -> Any:
    """A tool call's read deadline as the installed SDK takes it."""
    return value.total_seconds() if SDK == 2 else value


def structured(result: Any) -> Any:
    """A tool result's structured content (`structuredContent` in SDK 1, `structured_content` in SDK 2)."""
    return getattr(result, "structured_content", None) if SDK == 2 else getattr(result, "structuredContent", None)


def is_error(result: Any) -> bool:
    """Whether a tool result is an error (`isError` in SDK 1, `is_error` in SDK 2)."""
    return bool(getattr(result, "is_error", None) if SDK == 2 else getattr(result, "isError", None))
