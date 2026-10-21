"""JSON search: preserved A/B baseline and opt-in bounded Agent. SSE follows."""

import asyncio
from contextlib import asynccontextmanager
import logging
import os
import time
from uuid import uuid4

from fastapi import FastAPI, HTTPException

from backend.app.mcp.client import connect
from backend.app.schemas import MetadataReply, SearchRequest, SearchResponse
from backend.app.services.search import SearchFailure, call_tool as call, search_and_verify
from backend.app.services.video_catalog import load_videos
from backend.app.agent.graph import FinderAgent
from backend.app.agent.model import OllamaModel
from backend.app.agent.telemetry import TelemetryPublisher

logger = logging.getLogger("wish_finder")


@asynccontextmanager
async def lifespan(app):
    app.state.session = None
    app.state.busy = False
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
                model = OllamaModel(os.getenv('WISH_LLM_MODEL','qwen3:8b'))
                await model.ready()
                telemetry = await TelemetryPublisher().start()
                app.state.agent = FinderAgent(session,app.state.videos,model,
                    mode='keyword' if os.getenv('WISH_KEYWORD_ONLY')=='1' else 'hybrid',
                    tool_call=call,telemetry=telemetry)
            yield
        finally:
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
    return {"status":"ready","stage":"agent_json" if app.state.agent else "day1_retrieval"}


@app.get('/api/videos')
async def videos():
    ready()
    return {"videos":[video.model_dump() for video in app.state.videos.values()]}


@app.post('/api/search',response_model=SearchResponse)
async def search(request: SearchRequest):
    ready()
    # No await between check/set: atomic on this single-worker event loop.
    if app.state.busy:
        raise HTTPException(503,"다른 검색이 진행 중입니다. 잠시 후 다시 시도해 주세요.")
    app.state.busy=True
    request_id=str(uuid4());start=time.monotonic()
    try:
        mode='keyword' if os.getenv('WISH_KEYWORD_ONLY')=='1' else 'hybrid'
        if app.state.agent is not None:
            response, _ = await app.state.agent.run(request.query,request_id=request_id)
            return response
        execution = await search_and_verify(app.state.session, request.query, mode,
            app.state.videos, request_id=request_id, tool_call=call)
        return execution.response
    except SearchFailure as exc:
        logger.warning('search_failed request_id=%s code=%s', request_id, exc.code)
        if exc.code == 'search_busy':
            message = '이전 검색을 마무리 중입니다. 잠시 후 다시 시도해 주세요.'
        elif exc.code.startswith('model_'):
            message = '의미 검증 모델에 오류가 발생했습니다. 다시 시도해 주세요.'
        elif exc.code == 'agent_failure':
            message = '검색 처리 중 오류가 발생했습니다. 다시 시도해 주세요.'
        else:
            message = '검색 도구에 오류가 발생했습니다. 다시 시도해 주세요.'
        raise HTTPException(503,detail={'request_id':request_id,'message':message,'code':exc.code}) from None
    finally:
        app.state.busy=False
        logger.info('search request_id=%s elapsed_seconds=%.3f',request_id,time.monotonic()-start)
