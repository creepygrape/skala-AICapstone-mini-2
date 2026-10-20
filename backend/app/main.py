"""Day 1 JSON search slice. Full semantic graph and POST SSE follow on Day 2."""

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import time
from uuid import uuid4

from fastapi import FastAPI, HTTPException

from backend.app.mcp.client import connect
from backend.app.schemas import (ContextReply, MetadataReply, SearchReply,
                                 SearchRequest, SearchResponse)
from backend.app.services.evidence import verify_candidate
from backend.app.services.video_catalog import load_videos

logger = logging.getLogger("wish_finder")


async def call(session, name, arguments, schema):
    result = await session.call_tool(name, arguments, read_timeout_seconds=30)
    if result.is_error or result.structured_content is None:
        raise RuntimeError(f"MCP tool failed: {name}")
    return schema.model_validate(result.structured_content)


@asynccontextmanager
async def lifespan(app):
    app.state.session = None
    app.state.busy = False
    app.state.startup_error = None
    app.state.video_ids = [v.video_id for v in load_videos(Path(os.environ['WISH_MANIFEST']) if os.getenv('WISH_MANIFEST') else None)]
    env = {key:value for key,value in os.environ.items() if key.startswith('WISH_')}
    env.update(HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",TOKENIZERS_PARALLELISM="false")
    # Enter/exit transport and session in this lifespan task, not a child wait_for task.
    async with connect(env=env) as session:
        app.state.session = session
        await session.list_tools()
        yield
        app.state.session = None


app = FastAPI(title="WISH FINDER", lifespan=lifespan)


@app.get('/health')
def health():
    return {"status":"ok"}


@app.get('/ready')
def ready():
    if getattr(app.state,'session',None) is None:
        raise HTTPException(503,"검색 서버가 준비되지 않았습니다.")
    return {"status":"ready","stage":"day1_retrieval"}


@app.get('/api/videos')
async def videos():
    ready()
    # The server owns the only catalog/model instance; use its registered tool.
    items=[]
    for video_id in app.state.video_ids:
        try:
            item=await call(app.state.session,'get_video_metadata',{'video_id':video_id},MetadataReply)
        except Exception:
            raise HTTPException(503,"등록 영상 목록을 읽을 수 없습니다.") from None
        items.append(item.model_dump())
    return {"videos":items}


@app.post('/api/search',response_model=SearchResponse)
async def search(request: SearchRequest):
    ready()
    # No await between check/set: atomic on this single-worker event loop.
    if app.state.busy:
        raise HTTPException(503,"다른 검색이 진행 중입니다. 잠시 후 다시 시도해 주세요.")
    app.state.busy=True
    request_id=str(uuid4());start=time.monotonic()
    try:
        async with asyncio.timeout(60):
            mode='keyword' if os.getenv('WISH_KEYWORD_ONLY')=='1' else 'hybrid'
            reply=await call(app.state.session,'search_transcripts',{'query':request.query,'mode':mode,'top_k':3},SearchReply)
            results=[]
            for candidate in reply.candidates:
                context=await call(app.state.session,'get_scene_context',{
                    'video_id':candidate.chunk.video_id,'start_seconds':candidate.chunk.start_seconds,
                    'window_seconds':20},ContextReply)
                metadata=await call(app.state.session,'get_video_metadata',{'video_id':candidate.chunk.video_id},MetadataReply)
                results.append(verify_candidate(candidate,context,metadata))
            return SearchResponse(request_id=request_id,status='partial' if results else 'not_found',
                                  search_attempts=1,results=results,
                                  warnings=['semantic_verification_skipped','speaker_unknown','video_timing_unverified'])
    except Exception:
        logger.exception('search_failed request_id=%s',request_id)
        raise HTTPException(503,detail={'request_id':request_id,'message':'검색 도구에 오류가 발생했습니다. 다시 시도해 주세요.'}) from None
    finally:
        app.state.busy=False
        logger.info('search request_id=%s elapsed_seconds=%.3f',request_id,time.monotonic()-start)
