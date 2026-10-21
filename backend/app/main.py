"""Shared JSON and POST SSE search with bounded Agent and A/B baselines."""

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import time
from uuid import uuid4

from fastapi import FastAPI, HTTPException

from backend.app.mcp.client import connect
from backend.app.schemas import MetadataReply, SearchRequest, SearchResponse
from backend.app.services.search import SearchFailure, call_tool as call, search_and_verify
from backend.app.services.video_catalog import ROOT, load_videos
from backend.app.agent.graph import FinderAgent
from backend.app.agent.model import build_model
from backend.app.agent.telemetry import TelemetryPublisher
from backend.app.sse import MESSAGES, ManagedStreamingResponse, StreamOwner, encode_event, public_error

logger = logging.getLogger("wish_finder")


def trace_dir(value):
    """Traces contain subtitle text, so only Git-ignored private locations are allowed."""
    if not value:
        return None
    target = Path(value) if Path(value).is_absolute() else ROOT/value
    target = target.resolve()
    allowed = [(ROOT/'eval/private').resolve(), (ROOT/'logs').resolve()]
    if not any(target.is_relative_to(root) for root in allowed):
        logger.warning('agent_trace_disabled reason=path_not_private')
        return None
    return target


@asynccontextmanager
async def lifespan(app):
    app.state.session = None
    app.state.busy = False
    app.state.search_tasks = set()
    app.state.video_ids = [v.video_id for v in load_videos()]
    app.state.videos = {}
    app.state.agent = None
    model = None
    telemetry = None
    env = {key:value for key,value in os.environ.items() if key.startswith('WISH_')}
    env.update(HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",TOKENIZERS_PARALLELISM="false")
    # Enter/exit transport and session in this lifespan task, not a child wait_for task.
    async with connect(env=env) as session:
        app.state.session = session
        try:
            async with asyncio.timeout(30):
                await session.list_tools()
            for video_id in app.state.video_ids:
                video = await call(session,'get_video_metadata',{'video_id':video_id},MetadataReply)
                app.state.videos[video_id] = video
            if os.getenv('WISH_AGENT_ENABLED') == '1':
                model = build_model()
                await model.ready()
                telemetry = await TelemetryPublisher().start()
                app.state.agent = FinderAgent(session,app.state.videos,model,
                    mode='keyword' if os.getenv('WISH_KEYWORD_ONLY')=='1' else 'hybrid',
                    tool_call=call,telemetry=telemetry,
                    trace_dir=trace_dir(os.getenv('WISH_AGENT_TRACE')))
            yield
        finally:
            tasks = list(app.state.search_tasks)
            for task in tasks:
                if not task.cancelling():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if model is not None:
                await model.close()
            if telemetry is not None:
                await telemetry.close()
            app.state.agent = None
            app.state.session = None
            app.state.videos = {}


app = FastAPI(title="WISH FINDER", lifespan=lifespan)


@app.get('/health')
def health():
    return {"status":"ok"}


@app.get('/ready')
def ready():
    if getattr(app.state,'session',None) is None:
        raise HTTPException(503,"검색 서버가 준비되지 않았습니다.")
    agent = app.state.agent
    return {"status":"ready","stage":"agent_json" if agent else "day1_retrieval",
            "llm_backend":getattr(getattr(agent,'model',None),'name',None)}


@app.get('/api/videos')
async def videos():
    ready()
    return {"videos":[video.model_dump() for video in app.state.videos.values()]}


async def run_search(query: str, request_id: str, progress=None, timings=None) -> SearchResponse:
    """Run the shared JSON/SSE pipeline; raise only safe SearchFailure errors."""
    started = time.monotonic()
    try:
        if app.state.agent is not None:
            kwargs = {'request_id': request_id}
            if progress is not None:
                kwargs['progress'] = progress
            response, record = await app.state.agent.run(query, **kwargs)
            if timings is not None:
                timings['stage_ms'] = record.get('stage_tail_ms', {})
            return response
        mode = 'keyword' if os.getenv('WISH_KEYWORD_ONLY') == '1' else 'hybrid'
        execution = await search_and_verify(app.state.session, query, mode,
            app.state.videos, request_id=request_id, tool_call=call, progress=progress)
        return execution.response
    except SearchFailure as exc:
        logger.warning('search_failed request_id=%s code=%s', request_id, exc.code)
        raise
    except Exception as exc:
        logger.exception('search_failed request_id=%s code=agent_failure', request_id)
        raise SearchFailure('agent_failure') from exc
    finally:
        logger.info('search request_id=%s elapsed_seconds=%.3f',
                    request_id, time.monotonic()-started)


def reserve_search():
    """Reserve one search atomically on the single-worker event loop."""
    ready()
    if app.state.busy:
        raise HTTPException(503, '다른 검색이 진행 중입니다. 잠시 후 다시 시도해 주세요.')
    app.state.busy = True


@app.post('/api/search', response_model=SearchResponse)
async def search(request: SearchRequest):
    reserve_search()
    request_id = str(uuid4())
    try:
        return await run_search(request.query, request_id)
    except SearchFailure as exc:
        code, message = public_error(exc)
        raise HTTPException(503, detail={'request_id':request_id,
            'message':message, 'code':code}) from None
    finally:
        app.state.busy = False


@app.post('/api/search/stream')
async def search_stream(request: SearchRequest):
    """Stream public progress; response lifetime owns cancellation and reservation."""
    reserve_search()
    request_id = str(uuid4())
    queue = asyncio.Queue(maxsize=32)

    def release():
        app.state.busy = False

    owner = StreamOwner(release, getattr(app.state, 'search_tasks', None))

    started = time.monotonic()
    timings = {}

    def elapsed_ms():
        return int((time.monotonic()-started)*1000)

    async def progress(event, payload):
        await queue.put((event, {'request_id':request_id,
            'message':MESSAGES[event], **payload, 'elapsed_ms':elapsed_ms()}))

    async def execute():
        try:
            response = await run_search(request.query, request_id, progress, timings)
            await queue.put(('result', response.model_dump()))
            done = {'request_id':request_id, 'status':response.status, 'elapsed_ms':elapsed_ms()}
            if timings.get('stage_ms'):
                done['stage_ms'] = timings['stage_ms']
            await queue.put(('done', done))
        except SearchFailure as exc:
            code, message = public_error(exc)
            await queue.put(('error', {'request_id':request_id, 'code':code, 'message':message}))
            await queue.put(('done', {'request_id':request_id, 'status':'error',
                'elapsed_ms':elapsed_ms()}))

    async def events():
        owner.start(execute())
        try:
            while True:
                event, data = await queue.get()
                yield encode_event(event, data)
                if event == 'done':
                    break
        finally:
            await owner.close()

    return ManagedStreamingResponse(events(), owner=owner,
        media_type='text/event-stream', headers={
            'Cache-Control':'no-cache', 'X-Accel-Buffering':'no'})
