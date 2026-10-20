"""Integration test uses a real subprocess, stdio and LangGraph node."""

import asyncio
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from backend.app.mcp.client import connect


class ProbeState(TypedDict):
    response: dict


def test_real_stdio_via_langgraph():
    async def run():
        async with connect("backend.tests.mcp_probe") as session:
            tools = await session.list_tools()
            assert [t.name for t in tools.tools] == ["probe"]

            async def call_probe(state):
                result = await session.call_tool("probe", {"message": "연결 확인"})
                assert not result.is_error
                return {"response": result.structured_content}

            builder = StateGraph(ProbeState)
            builder.add_node("call_probe", call_probe)
            builder.add_edge(START, "call_probe")
            builder.add_edge("call_probe", END)
            graph = builder.compile()
            for _ in range(2):
                state = await graph.ainvoke({})
                assert state["response"] == {"message": "연결 확인", "synthetic": True}

    asyncio.run(asyncio.wait_for(run(), timeout=25))


def test_slow_startup_and_timed_out_worker_rejects_overlapping_search():
    async def run():
        async with connect('backend.tests.mcp_slow_probe', initialization_timeout=5) as session:
            try:
                await session.call_tool('slow_search', {}, read_timeout_seconds=.05)
            except Exception:
                pass  # Client stops waiting; the server worker still holds the gate.
            else:
                raise AssertionError('Slow worker should exceed per-tool timeout')
            start = time.monotonic()
            overlap = await session.call_tool('slow_search', {}, read_timeout_seconds=1)
            assert overlap.is_error
            assert any('search_busy' in getattr(c,'text','') for c in overlap.content)
            assert time.monotonic()-start < .3  # No second calculation or queue.
            await asyncio.sleep(.45)
            recovered = await session.call_tool('slow_search', {}, read_timeout_seconds=1)
            assert not recovered.is_error and recovered.structured_content == {'completed':True}

    asyncio.run(asyncio.wait_for(run(), timeout=8))
