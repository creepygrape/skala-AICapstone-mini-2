"""The same Day 1 search/verification pipeline for JSON API and evaluation."""

import asyncio
from dataclasses import dataclass
from uuid import uuid4

import anyio
from mcp.shared.exceptions import MCPError
from mcp.types import CONNECTION_CLOSED, REQUEST_TIMEOUT

from backend.app.schemas import ContextReply, SearchReply, SearchRequest, SearchResponse
from backend.app.services.evidence import verify_candidate


class SearchFailure(RuntimeError):
    """Safe error classification; raw peer exceptions must not enter results."""
    def __init__(self, code: str, *, fatal: bool = False, tool_calls: int = 0, search_attempts: int = 0):
        super().__init__(code)
        self.code, self.fatal, self.tool_calls = code, fatal, tool_calls
        self.search_attempts = search_attempts


async def call_tool(session, name, arguments, schema):
    """Call one real MCP tool; distinguish execution failure from a lost session."""
    try:
        result = await session.call_tool(name, arguments, read_timeout_seconds=30)
    except MCPError as exc:
        code = 'transport_closed' if exc.code == CONNECTION_CLOSED else (
            'tool_timeout' if exc.code == REQUEST_TIMEOUT else 'protocol_error')
        raise SearchFailure(code, fatal=exc.code == CONNECTION_CLOSED) from exc
    except (anyio.BrokenResourceError, anyio.ClosedResourceError, anyio.EndOfStream, EOFError) as exc:
        raise SearchFailure('transport_closed', fatal=True) from exc
    if result.is_error:
        busy = any('search_busy:' in getattr(c, 'text', '') for c in result.content)
        raise SearchFailure('search_busy' if busy else 'tool_failure')
    if result.structured_content is None:
        raise SearchFailure('invalid_tool_response')
    try:
        return schema.model_validate(result.structured_content)
    except ValueError as exc:
        raise SearchFailure('invalid_tool_response') from exc


@dataclass
class SearchExecution:
    response: SearchResponse
    query: str
    tool_calls: int
    video_timing: dict[str, str]


async def search_and_verify(session, query, mode, metadata, *, request_id=None, tool_call=call_tool):
    """Normalize input and verify each source candidate, never infer meaning/speaker.

    Invalid requests raise Pydantic validation errors. Candidate grounding failures
    are omitted with warnings; tool/session failures raise SearchFailure with the
    attempted call count. The same 60s budget applies to API and evaluation.
    """
    query = SearchRequest(query=query).query
    request_id = request_id or str(uuid4())
    calls = 0
    rounds = 0

    async def counted(name, arguments, schema):
        nonlocal calls
        calls += 1
        return await tool_call(session, name, arguments, schema)

    try:
        async with asyncio.timeout(60):
            reply = await counted('search_transcripts', {'query': query, 'mode': mode, 'top_k': 3}, SearchReply)
            rounds = 1
            results, timing = [], {}
            warnings = ['semantic_verification_skipped', 'speaker_unknown']
            for candidate in reply.candidates:
                video = metadata.get(candidate.chunk.video_id)
                if video is None:
                    if 'evidence_rejected' not in warnings:
                        warnings.append('evidence_rejected')
                    continue
                context = await counted('get_scene_context', {
                    'video_id': candidate.chunk.video_id,
                    'start_seconds': candidate.chunk.start_seconds,
                    'window_seconds': 20,
                }, ContextReply)
                try:
                    result = verify_candidate(candidate, context, video)
                except ValueError:
                    if 'evidence_rejected' not in warnings:
                        warnings.append('evidence_rejected')
                    continue
                results.append(result)
                # Only surviving results contribute timing claims/warnings.
                sampled = video.timing_verified
                timing[result.video_id] = 'sampled' if sampled else 'unverified'
                warning = 'video_timing_sampled' if sampled else 'video_timing_unverified'
                if warning not in warnings:
                    warnings.append(warning)
            status = 'partial' if results else ('unsupported' if reply.candidates else 'not_found')
            return SearchExecution(SearchResponse(request_id=request_id, status=status,
                search_attempts=1, results=results, warnings=warnings), query, calls, timing)
    except SearchFailure as exc:
        exc.tool_calls = calls
        exc.search_attempts = rounds
        raise
    except TimeoutError as exc:
        raise SearchFailure('request_timeout', tool_calls=calls, search_attempts=rounds) from exc
    except Exception as exc:
        raise SearchFailure('search_failure', tool_calls=calls, search_attempts=rounds) from exc
