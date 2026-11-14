"""B-140: a refused handshake closes the transport in the task that opened it; the job says why it failed."""
from contextlib import asynccontextmanager

import pytest

from research_agent import prowl_client as pc
from research_agent.service.runtime import _cause


async def test_a_refused_handshake_closes_what_it_opened(monkeypatch):
    events = []

    @asynccontextmanager
    async def streams(url, headers):
        events.append("open")
        try:
            yield ("read", "write")
        finally:
            events.append("closed")

    class Session:
        def __init__(self, read, write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            events.append("session closed")

        async def initialize(self):
            raise RuntimeError("401 Invalid or revoked API key.")

    monkeypatch.setattr(pc, "open_streams", streams)
    monkeypatch.setattr(pc, "ClientSession", Session)
    client = pc.ProwlClient(api_key="k", mcp_url="https://prowl.invalid/mcp")
    with pytest.raises(RuntimeError, match="Invalid or revoked"):
        await client.__aenter__()
    assert events == ["open", "session closed", "closed"]  # closed now, in this task, not by the collector later
    assert client._stack is None and client._session is None


def test_the_cause_comes_before_the_advice_and_holds_no_secret():
    class MCPError(Exception):
        pass

    assert _cause(MCPError("Invalid or revoked API key.")) == "MCPError: Invalid or revoked API key. "
    assert "prowl_abcdefghijkl" not in _cause(MCPError("bad key prowl_abcdefghijkl"))
    assert _cause(MCPError()) == "MCPError. "
    assert len(_cause(MCPError("x" * 500))) <= 182
