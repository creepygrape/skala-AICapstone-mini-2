"""Synthetic transport probe; never presented as actual transcript search."""

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

server = MCPServer("wish-finder-synthetic-probe")


class ProbeReply(BaseModel):
    message: str
    synthetic: bool = True


@server.tool(structured_output=True)
def probe(message: str) -> ProbeReply:
    """Echo a synthetic diagnostic message; no video data or model access."""
    return ProbeReply(message=message)


if __name__ == "__main__":
    server.run(transport="stdio")
