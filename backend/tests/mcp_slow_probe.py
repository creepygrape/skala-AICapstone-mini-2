"""Synthetic slow worker for real stdio cancellation/overlap regression tests."""

import time

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel
from backend.app.mcp.search_gate import SearchGate

server = MCPServer('wish-finder-slow-test')
gate = SearchGate()


class Reply(BaseModel):
    completed: bool


@server.tool(structured_output=True)
def slow_search() -> Reply:
    """Simulate synchronous model work, rejecting overlaps without a queue."""
    with gate.acquire():
        time.sleep(.4)
        return Reply(completed=True)


if __name__ == '__main__':
    time.sleep(.2)  # Startup can legitimately exceed a per-tool timeout.
    server.run(transport='stdio')
