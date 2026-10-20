"""Long-lived official SDK 2.x stdio sessions; no per-tool subprocess."""

from contextlib import asynccontextmanager
from pathlib import Path
import sys

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[3]


@asynccontextmanager
async def connect(module: str = "backend.app.mcp.server", env: dict | None = None):
    """Initialize one stdio session and close it in its owning task.

    Raises SDK/transport errors on startup or communication failure.
    The executable is the current Python, so the project's .venv is reused.
    """
    params = StdioServerParameters(
        command=sys.executable, args=["-m", module], cwd=ROOT, env=env
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=30) as session:
            await session.initialize()
            yield session
