"""Long-lived official SDK 2.x stdio sessions; no per-tool subprocess."""

from contextlib import asynccontextmanager, nullcontext
from pathlib import Path
import sys

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[3]


def child_stderr():
    """Where the MCP subprocess writes its stderr.

    Windows: an inherited console stderr has made the child die silently ("Connection closed")
    on some terminals, so it goes to a Git-ignored file that also keeps the real failure cause.
    Elsewhere the child keeps sharing this process's stderr.
    """
    if sys.platform != "win32":
        return nullcontext(sys.stderr)
    path = ROOT / "logs/mcp_server.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("a", encoding="utf-8", errors="replace")


@asynccontextmanager
async def connect(module: str = "backend.app.mcp.server", env: dict | None = None,
                  initialization_timeout: float = 180):
    """Initialize one stdio session and close it in its owning task.

    Raises SDK/transport errors on startup or communication failure.
    The executable is the current Python, so the project's .venv is reused.
    """
    params = StdioServerParameters(
        command=sys.executable, args=["-m", module], cwd=ROOT, env=env
    )
    with child_stderr() as errlog:
        async with stdio_client(params, errlog=errlog) as (read, write):
            # The first launch can build the dense index before replying. API tool
            # calls set their own shorter timeout; do not apply that to initialize.
            async with ClientSession(read, write, read_timeout_seconds=initialization_timeout) as session:
                await session.initialize()
                yield session
