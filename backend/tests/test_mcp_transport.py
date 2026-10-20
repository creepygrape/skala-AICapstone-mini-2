"""Integration test uses a real subprocess, stdio and LangGraph node."""

import asyncio
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
