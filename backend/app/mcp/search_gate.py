"""Protect synchronous model/cache work even after the client stops waiting."""

from contextlib import contextmanager
from threading import Lock
from mcp.server.mcpserver.exceptions import ToolError


class SearchBusyError(ToolError):
    """Expected fail-fast refusal; safe for the MCP client to see."""


class SearchGate:
    def __init__(self):
        self._lock = Lock()

    @contextmanager
    def acquire(self):
        """Fail fast while a worker is running; never queue model calculations."""
        if not self._lock.acquire(blocking=False):
            raise SearchBusyError("search_busy: previous search is still running")
        try:
            yield
        finally:
            self._lock.release()
