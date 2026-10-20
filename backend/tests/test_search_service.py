"""API/evaluation parity under the same synthetic MCP responses and failures."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient
from mcp.shared.exceptions import MCPError
from mcp.types import CONNECTION_CLOSED
import pytest

from backend.app.services.search import search_and_verify
from backend.app.services.video_catalog import Catalog, ROOT
from backend.app.retrieval.hybrid import Retriever
from backend.app.schemas import ContextReply, MetadataReply
from eval.dataset import load_questions
from eval.run_eval import evaluate_question


class FakeSession:
    """Transport test double; real stdio tests remain in test_api/transport."""
    def __init__(self, behavior='normal', fail_search_number=None):
        self.catalog = Catalog(ROOT/'data/manifest.example.json')
        self.retriever = Retriever(self.catalog)
        self.behavior, self.fail_search_number = behavior, fail_search_number
        self.queries = []

    async def list_tools(self):
        return SimpleNamespace(tools=[])

    async def call_tool(self,name,args,read_timeout_seconds=30):
        if name == 'get_video_metadata':
            v=self.catalog.videos[args['video_id']]
            body=MetadataReply(video_id=v.video_id,title=v.title,url=v.url,
                               title_verified=False,timing_verified=v.timing_verified)
        elif name == 'get_scene_context':
            cues=self.catalog.context(args['video_id'],args['start_seconds'],args['window_seconds'])
            body=ContextReply(video_id=args['video_id'],cues=cues)
        else:
            self.queries.append(args['query'])
            fail=self.fail_search_number is None or len(self.queries)==self.fail_search_number
            if self.behavior=='fatal' and fail:
                raise MCPError(CONNECTION_CLOSED,'synthetic closed connection')
            if self.behavior=='tool_error' and fail:
                return SimpleNamespace(is_error=True,structured_content=None,content=[])
            body=self.retriever.search(args['query'],'keyword')
            if self.behavior=='empty':
                body.candidates=[]
            elif self.behavior in {'one_invalid','all_invalid'}:
                bad=body.candidates[0].model_copy(deep=True)
                bad.selected_cue_id='missing'
                body.candidates=[bad] if self.behavior=='all_invalid' else [bad,*body.candidates]
        return SimpleNamespace(is_error=False,structured_content=body.model_dump(),content=[])


@pytest.mark.parametrize('behavior,expected',[
    ('normal','partial'),('one_invalid','partial'),('all_invalid','unsupported'),
    ('empty','not_found'),('tool_error','error'),('fatal','error'),
])
def test_api_and_evaluation_share_status_warnings_and_results(monkeypatch,behavior,expected):
    import backend.app.main as main
    session=FakeSession(behavior)
    @asynccontextmanager
    async def fake_connect(**kwargs): yield session
    monkeypatch.setenv('WISH_MANIFEST','data/manifest.example.json')
    monkeypatch.setenv('WISH_KEYWORD_ONLY','1')
    monkeypatch.setattr(main,'connect',fake_connect)
    question=load_questions(ROOT/'eval/dataset.example.jsonl')[0]
    with TestClient(main.app) as client:
        response=client.post('/api/search',json={'query':' \nRIKU chose RIKU\n '})
        metadata=main.app.state.videos.copy()
    record=asyncio.run(evaluate_question(session,question,' \nRIKU chose RIKU\n ','keyword',metadata,
                                         condition='raw_ko',system='A'))
    assert record['status']==expected
    if expected=='error':
        assert response.status_code==503
        assert record['error']['code']==response.json()['detail']['code']
    else:
        body=response.json()
        assert record['status']==body['status']
        assert record['warnings']==body['warnings']
        assert [r['cue_ids'] for r in record['results']]==[r['cue_ids'] for r in body['results']]
    assert session.queries==['RIKU chose RIKU','RIKU chose RIKU']


@pytest.mark.parametrize('query',[' \n ','x'*1001])
def test_invalid_query_has_same_validation_and_no_search(monkeypatch,query):
    import backend.app.main as main
    session=FakeSession()
    @asynccontextmanager
    async def fake_connect(**kwargs): yield session
    monkeypatch.setenv('WISH_MANIFEST','data/manifest.example.json')
    monkeypatch.setattr(main,'connect',fake_connect)
    with TestClient(main.app) as client:
        assert client.post('/api/search',json={'query':query}).status_code==422
        metadata=main.app.state.videos.copy()
    question=load_questions(ROOT/'eval/dataset.example.jsonl')[0]
    record=asyncio.run(evaluate_question(session,question,query,'keyword',metadata,condition='raw_ko',system='A'))
    assert record['error']['code']=='invalid_query'
    assert record['tool_calls']==0 and session.queries==[]


def test_only_verified_survivors_contribute_timing_warnings():
    session=FakeSession('one_invalid')
    v=session.catalog.videos['SYNTHETIC01']
    good=MetadataReply(video_id=v.video_id,title=v.title,url=v.url,title_verified=False,timing_verified=True)
    bad=good.model_copy(update={'video_id':'SYNTHETIC02','timing_verified':False})
    original=session.call_tool
    async def inject(name,args,**kwargs):
        reply=await original(name,args,**kwargs)
        if name=='search_transcripts':
            reply.structured_content['candidates'][0]['chunk']['video_id']='SYNTHETIC02'
        if name=='get_scene_context' and args['video_id']=='SYNTHETIC02':
            return SimpleNamespace(is_error=False,content=[],structured_content={'video_id':'SYNTHETIC02','cues':[]})
        return reply
    # Handle the rejected video's context without querying the fixture catalog.
    async def calls(session_,name,args,schema):
        if name=='get_scene_context' and args['video_id']=='SYNTHETIC02':
            return ContextReply(video_id='SYNTHETIC02',cues=[])
        return schema.model_validate((await inject(name,args)).structured_content)
    result=asyncio.run(search_and_verify(session,'RIKU','keyword',
        {good.video_id:good,bad.video_id:bad},tool_call=calls))
    assert result.response.results
    assert 'video_timing_sampled' in result.response.warnings
    assert 'video_timing_unverified' not in result.response.warnings
    assert result.video_timing=={'SYNTHETIC01':'sampled'}
