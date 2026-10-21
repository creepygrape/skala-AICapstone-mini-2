"""Bounded Graph/API tests: scripted semantic model, real MCP where specified."""

import asyncio
import json

from fastapi.testclient import TestClient
import httpx
import pytest

from backend.app.agent.graph import FinderAgent
from backend.app.agent.model import OllamaModel, Route, Verification, Judgment
from backend.app.schemas import MetadataReply
from backend.app.services.search import SearchFailure
from backend.tests.test_search_service import FakeSession


class ScriptedModel:
    def __init__(self, verdicts=('relevant',), intent='scene_search', *, same_query=False):
        self.verdicts, self.intent, self.same_query = verdicts, intent, same_query
        self.verifications = 0
        self.rewrites = 0
        self.closed = False

    async def ready(self): pass
    async def close(self): self.closed=True

    async def route(self, query):
        return Route(intent=self.intent,search_query='RIKU chose RIKU')

    async def verify(self, query, evidence):
        verdict=self.verdicts[min(self.verifications,len(self.verdicts)-1)]
        self.verifications+=1
        return Verification(judgments=[Judgment(evidence_id=e['evidence_id'],verdict=verdict) for e in evidence])

    async def rewrite(self, query, previous, feedback):
        self.rewrites+=1
        return previous[-1] if self.same_query else f'RIKU chose RIKU scene {self.rewrites}'


def make_agent(tmp_path, model=None, behavior='normal', **kwargs):
    session=FakeSession(behavior)
    v=session.catalog.videos['SYNTHETIC01']
    metadata={v.video_id:MetadataReply(video_id=v.video_id,title=v.title,url=v.url,
        title_verified=False,timing_verified=True)}
    return FinderAgent(session,metadata,model or ScriptedModel(),mode='keyword',
                       log_path=tmp_path/'agent.jsonl',**kwargs),session


@pytest.mark.parametrize('verdicts,attempts,status',[
    (('relevant',),1,'found'),(('irrelevant','relevant'),2,'found'),
    (('irrelevant','irrelevant','relevant'),3,'found'),
    (('irrelevant',),3,'not_found'),(('uncertain',),3,'ambiguous'),
])
def test_bounded_graph_paths_and_grounded_results(tmp_path,verdicts,attempts,status):
    model=ScriptedModel(verdicts)
    agent,session=make_agent(tmp_path,model)
    response,stats=asyncio.run(agent.run('기억나는 장면'))
    assert response.status==status
    assert response.search_attempts==attempts==len(session.queries)
    assert model.rewrites==attempts-1
    assert stats['llm_calls']==1+attempts+attempts-1
    assert stats['tool_calls']>=attempts*2
    assert [s['attempt'] for s in stats['stages'] if s['node']=='search']==list(range(attempts))
    assert 'semantic_verification_skipped' not in response.warnings
    for result in response.results:
        assert result.evidence_text in {c.original_text for c in session.catalog.cues[result.video_id]}
        assert result.speaker is None
    record=json.loads((tmp_path/'agent.jsonl').read_text())
    assert '기억나는 장면' not in json.dumps(record,ensure_ascii=False)
    assert 'original_text' not in record


def test_speaker_keeps_scene_and_explicit_limit(tmp_path):
    agent,_=make_agent(tmp_path,ScriptedModel(intent='speaker_query'))
    response,stats=asyncio.run(agent.run('누가 말했어?'))
    assert stats['intent']=='speaker_query'
    assert response.results and response.status=='found'
    assert 'speaker_unknown' in response.warnings
    assert all('자막만으로 화자를 확인할 수 없습니다' in r.explanation_ko for r in response.results)
    assert all(r.speaker is None for r in response.results)


@pytest.mark.parametrize('intent',['unsupported','chat'])
def test_scope_router_does_not_search(tmp_path,intent):
    agent,session=make_agent(tmp_path,ScriptedModel(intent=intent))
    response,stats=asyncio.run(agent.run('어떤 옷을 입었어?'))
    assert response.status=='unsupported' and response.search_attempts==0
    assert not session.queries and stats['tool_calls']==0
    assert stats['llm_calls']==1


def test_duplicate_rewrite_stops_without_repeating_search(tmp_path):
    agent,session=make_agent(tmp_path,ScriptedModel(('irrelevant',),same_query=True))
    response,_=asyncio.run(agent.run('장면'))
    assert len(session.queries)==1 and response.search_attempts==1
    assert 'replan_query_unchanged' in response.warnings


@pytest.mark.parametrize('behavior,status',[('empty','not_found'),('all_invalid','unsupported')])
def test_no_candidates_and_rejected_source_never_reach_semantic_model(tmp_path,behavior,status):
    model=ScriptedModel()
    agent,session=make_agent(tmp_path,model,behavior)
    response,_=asyncio.run(agent.run('장면'))
    assert response.status==status and not response.results
    assert response.search_attempts==3 and model.verifications==0
    assert 'video_timing_sampled' not in response.warnings


def test_mcp_error_does_not_replan_or_return_partial(tmp_path):
    model=ScriptedModel()
    agent,_=make_agent(tmp_path,model,'tool_error')
    with pytest.raises(SearchFailure,match='tool_failure') as exc:
        asyncio.run(agent.run('장면'))
    assert exc.value.search_attempts==1 and exc.value.tool_calls==1
    assert model.rewrites==0
    assert json.loads((tmp_path/'agent.jsonl').read_text())['error']=='tool_failure'


def test_invalid_model_evidence_ids_are_not_accepted(tmp_path):
    model=ScriptedModel()
    async def invalid(*args):
        return Verification(judgments=[Judgment(evidence_id='invented',verdict='relevant')])
    model.verify=invalid
    agent,_=make_agent(tmp_path,model)
    with pytest.raises(SearchFailure,match='model_invalid_evidence_ids'):
        asyncio.run(agent.run('장면'))
    assert model.rewrites==0


def test_total_timeout_and_cancellation_are_not_not_found(tmp_path):
    model=ScriptedModel()
    async def slow(*args):
        await asyncio.sleep(1)
    model.route=slow
    agent,_=make_agent(tmp_path,model,timeout=.01)
    with pytest.raises(SearchFailure,match='request_timeout'):
        asyncio.run(agent.run('장면'))
    assert json.loads((tmp_path/'agent.jsonl').read_text())['search_attempts']==0
    async def cancel():
        task=asyncio.create_task(agent.run('장면'))
        await asyncio.sleep(.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(cancel())
    assert json.loads((tmp_path/'agent.jsonl').read_text().splitlines()[-1])['error']=='cancelled'


@pytest.mark.parametrize('failure',['timeout','malformed','http'])
def test_ollama_errors_are_typed_and_safe(failure):
    async def run():
        model=OllamaModel()
        await model.client.aclose()
        async def handle(request):
            if failure=='timeout': raise httpx.ReadTimeout('private text',request=request)
            if failure=='http': return httpx.Response(500,json={'secret':'private'})
            return httpx.Response(200,json={'message':{'content':'not JSON'}})
        model.client=httpx.AsyncClient(transport=httpx.MockTransport(handle),base_url='http://local')
        try:
            with pytest.raises(SearchFailure) as exc:
                await model.route('장면')
            assert exc.value.code=={'timeout':'model_timeout','malformed':'model_invalid_response','http':'model_unavailable'}[failure]
            assert 'private' not in str(exc.value)
        finally: await model.close()
    asyncio.run(run())


def test_agent_json_api_with_real_stdio_and_lifespan_cleanup(monkeypatch,tmp_path):
    import backend.app.main as main
    model=ScriptedModel(intent='speaker_query')
    monkeypatch.setenv('WISH_AGENT_ENABLED','1')
    monkeypatch.setenv('WISH_KEYWORD_ONLY','1')
    monkeypatch.setenv('WISH_MANIFEST','data/manifest.example.json')
    monkeypatch.setattr(main,'OllamaModel',lambda *args:model)
    calls=[]
    original=main.call
    async def record(session,name,args,schema):
        calls.append(name)
        return await original(session,name,args,schema)
    monkeypatch.setattr(main,'call',record)
    with TestClient(main.app) as client:
        main.app.state.agent.log_path=tmp_path/'agent.jsonl'
        assert client.get('/ready').json()['stage']=='agent_json'
        for _ in range(2):
            response=client.post('/api/search',json={'query':'누가 자기 자신을 뽑았다고 말했어?'})
            assert response.status_code==200,response.text
            body=response.json()
            assert body['status']=='found'
            assert body['results'][0]['url'].endswith('&t=3s')
        assert calls.count('get_video_metadata')==1  # lifespan cache
        assert calls.count('search_transcripts')==2
        assert 'get_scene_context' in calls
    assert model.closed and main.app.state.agent is None


def test_model_failure_in_api_is_503_and_releases_busy(monkeypatch,tmp_path):
    import backend.app.main as main
    model=ScriptedModel()
    async def fail(*args): raise SearchFailure('model_timeout')
    model.verify=fail
    monkeypatch.setenv('WISH_AGENT_ENABLED','1')
    monkeypatch.setenv('WISH_KEYWORD_ONLY','1')
    monkeypatch.setenv('WISH_MANIFEST','data/manifest.example.json')
    monkeypatch.setattr(main,'OllamaModel',lambda *args:model)
    with TestClient(main.app) as client:
        main.app.state.agent.log_path=tmp_path/'agent.jsonl'
        response=client.post('/api/search',json={'query':'RIKU'})
        assert response.status_code==503
        assert response.json()['detail']['code']=='model_timeout'
        assert 'results' not in response.json()
        assert not main.app.state.busy and model.rewrites==0
    assert model.closed


def test_model_startup_failure_closes_http_client(monkeypatch):
    import backend.app.main as main
    model=ScriptedModel()
    async def fail(): raise SearchFailure('model_unavailable')
    model.ready=fail
    monkeypatch.setenv('WISH_AGENT_ENABLED','1')
    monkeypatch.setenv('WISH_KEYWORD_ONLY','1')
    monkeypatch.setenv('WISH_MANIFEST','data/manifest.example.json')
    monkeypatch.setattr(main,'OllamaModel',lambda *args:model)
    with pytest.raises(Exception):
        with TestClient(main.app): pass
    assert model.closed and main.app.state.agent is None


def test_langsmith_is_explicit_opt_in_and_metadata_only(monkeypatch):
    import backend.app.agent.telemetry as telemetry
    records=[]
    class Client:
        def __init__(self,**kwargs): pass
        def create_run(self,**kwargs): records.append(kwargs)
        def close(self): pass
    monkeypatch.setattr(telemetry,'Client',Client)
    monkeypatch.setenv('LANGSMITH_API_KEY','synthetic-test-key')
    monkeypatch.delenv('WISH_LANGSMITH_ENABLED',raising=False)
    record={'request_id':'test','intent':'speaker_query','tool_calls':2}
    telemetry.publish_summary(record)
    assert not records
    monkeypatch.setenv('WISH_LANGSMITH_ENABLED','1')
    telemetry.publish_summary(record)
    assert records[0]['inputs']=={'source':'metadata_only'}
    assert records[0]['outputs']==record
