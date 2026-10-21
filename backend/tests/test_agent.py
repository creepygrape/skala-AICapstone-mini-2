"""Bounded Graph/API tests: scripted semantic model, real MCP where specified."""

import asyncio
import json
import time

from fastapi.testclient import TestClient
import httpx
import pytest

from backend.app.agent.graph import FinderAgent
from backend.app.agent.model import OllamaModel, Route, Verification, Judgment
from backend.app.agent.telemetry import TelemetryPublisher
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
    response,stats=asyncio.run(agent.run('장면'))
    assert response.status=='partial'
    assert 'semantic_model_error' in response.warnings
    assert 'semantic_verification_skipped' in response.warnings
    assert stats['error']=='model_invalid_evidence_ids'
    assert model.rewrites==0


def test_irrelevant_candidate_is_not_revived_when_rewrite_model_fails(tmp_path):
    model=ScriptedModel(('irrelevant',))
    async def fail(*args): raise SearchFailure('model_timeout')
    model.rewrite=fail
    agent,_=make_agent(tmp_path,model)
    with pytest.raises(SearchFailure,match='model_timeout'):
        asyncio.run(agent.run('장면'))
    record=json.loads((tmp_path/'agent.jsonl').read_text())
    assert record['status']=='error' and record['error']=='model_timeout'


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
    monkeypatch.setattr(main,'build_model',lambda *args,**kwargs:model)
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


@pytest.mark.parametrize('code',['model_timeout','model_invalid_response'])
def test_model_failure_after_grounding_returns_non_c_partial_and_releases_busy(
        monkeypatch,tmp_path,code):
    import backend.app.main as main
    model=ScriptedModel()
    async def fail(*args): raise SearchFailure(code)
    model.verify=fail
    monkeypatch.setenv('WISH_AGENT_ENABLED','1')
    monkeypatch.setenv('WISH_KEYWORD_ONLY','1')
    monkeypatch.setenv('WISH_MANIFEST','data/manifest.example.json')
    monkeypatch.setattr(main,'build_model',lambda *args,**kwargs:model)
    with TestClient(main.app) as client:
        main.app.state.agent.log_path=tmp_path/'agent.jsonl'
        response=client.post('/api/search',json={'query':'RIKU'})
        assert response.status_code==200
        assert response.json()['status']=='partial'
        assert 'semantic_model_error' in response.json()['warnings']
        assert response.json()['results']
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
    monkeypatch.setattr(main,'build_model',lambda *args,**kwargs:model)
    with pytest.raises(Exception):
        with TestClient(main.app): pass
    assert model.closed and main.app.state.agent is None


def test_model_router_failure_has_distinct_api_message(monkeypatch,tmp_path):
    import backend.app.main as main
    model=ScriptedModel()
    async def fail(*args): raise SearchFailure('model_unavailable')
    model.route=fail
    monkeypatch.setenv('WISH_AGENT_ENABLED','1')
    monkeypatch.setenv('WISH_KEYWORD_ONLY','1')
    monkeypatch.setenv('WISH_MANIFEST','data/manifest.example.json')
    monkeypatch.setattr(main,'build_model',lambda *args,**kwargs:model)
    with TestClient(main.app) as client:
        main.app.state.agent.log_path=tmp_path/'agent.jsonl'
        response=client.post('/api/search',json={'query':'RIKU'})
        assert response.status_code==503
        detail=response.json()['detail']
        assert detail['code']=='model_unavailable'
        assert '의미 검증 모델' in detail['message']
        assert not main.app.state.busy


def test_unexpected_agent_failure_has_distinct_api_message(monkeypatch,tmp_path):
    import backend.app.main as main
    model=ScriptedModel()
    async def fail(*args): raise RuntimeError('private implementation detail')
    model.route=fail
    monkeypatch.setenv('WISH_AGENT_ENABLED','1')
    monkeypatch.setenv('WISH_KEYWORD_ONLY','1')
    monkeypatch.setenv('WISH_MANIFEST','data/manifest.example.json')
    monkeypatch.setattr(main,'build_model',lambda *args,**kwargs:model)
    with TestClient(main.app) as client:
        main.app.state.agent.log_path=tmp_path/'agent.jsonl'
        response=client.post('/api/search',json={'query':'RIKU'})
        assert response.status_code==503
        detail=response.json()['detail']
        assert detail['code']=='agent_failure'
        assert '검색 처리 중 오류' in detail['message']
        assert 'private implementation detail' not in response.text


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


def test_replan_budget_preserves_uncertain_evidence(tmp_path):
    model=ScriptedModel(('uncertain',))
    agent,session=make_agent(tmp_path,model,min_replan_budget=10_000)
    response,stats=asyncio.run(agent.run('장면'))
    assert response.status=='ambiguous' and response.results
    assert response.search_attempts==1 and len(session.queries)==1
    assert model.rewrites==0
    assert 'replan_budget_exhausted' in response.warnings
    assert stats==json.loads((tmp_path/'agent.jsonl').read_text())


def test_total_timeout_preserves_previous_uncertain_evidence(tmp_path):
    model=ScriptedModel(('uncertain',))
    original=model.verify
    async def verify(query,evidence):
        if model.verifications:
            await asyncio.sleep(.2)
        return await original(query,evidence)
    model.verify=verify
    agent,_=make_agent(tmp_path,model,timeout=.05,min_replan_budget=0)
    response,stats=asyncio.run(agent.run('장면'))
    assert response.status=='ambiguous' and response.results
    assert response.search_attempts==2
    assert 'replan_budget_exhausted' in response.warnings
    assert stats['error']=='request_timeout'


def test_previous_rejection_does_not_change_later_not_found_or_leak_warning(tmp_path):
    agent,session=make_agent(tmp_path,ScriptedModel(('irrelevant',)))
    original=agent.tool_call
    searches=0
    async def changing(session_,name,args,schema):
        nonlocal searches
        result=await original(session_,name,args,schema)
        if name=='search_transcripts':
            searches+=1
            if searches==1:
                bad=result.candidates[0].model_copy(deep=True)
                bad.selected_cue_id='invalid'
                result.candidates=[bad,*result.candidates[1:]]
            else:
                result.candidates=[]
        return result
    agent.tool_call=changing
    response,_=asyncio.run(agent.run('장면'))
    assert response.status=='not_found'
    assert 'evidence_rejected' not in response.warnings
    assert len(session.queries)==3


def test_tagless_ollama_name_resolves_to_latest():
    async def run():
        model=OllamaModel('qwen3')
        await model.client.aclose()
        model.client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
            httpx.Response(200,json={'models':[{'name':'qwen3:latest','model':'qwen3:latest'}]})),
            base_url='http://local')
        try:
            await model.ready()
            assert model.model=='qwen3:latest'
        finally: await model.close()
    asyncio.run(run())


def test_telemetry_queue_does_not_delay_request_and_reuses_client(monkeypatch,tmp_path):
    import backend.app.agent.telemetry as telemetry
    clients=[];published=[]
    class Client:
        def __init__(self,**kwargs): clients.append(self)
        def close(self): pass
    def slow(record,client=None):
        time.sleep(.1);published.append((record,client))
    monkeypatch.setenv('WISH_LANGSMITH_ENABLED','1')
    monkeypatch.setenv('LANGSMITH_API_KEY','test')
    monkeypatch.setattr(telemetry,'Client',Client)
    monkeypatch.setattr(telemetry,'publish_summary',slow)
    async def run():
        publisher=await TelemetryPublisher().start()
        agent,_=make_agent(tmp_path,ScriptedModel(),telemetry=publisher)
        started=time.monotonic()
        await agent.run('장면')
        elapsed=time.monotonic()-started
        assert elapsed < .08
        await publisher.close()
        assert len(clients)==1 and len(published)==1 and published[0][1] is clients[0]
    asyncio.run(run())


def test_langsmith_start_failure_does_not_block_agent_api(monkeypatch,tmp_path):
    import backend.app.agent.telemetry as telemetry
    import backend.app.main as main
    model=ScriptedModel()
    class FailingClient:
        def __init__(self,**kwargs): raise RuntimeError('unavailable')
    monkeypatch.setenv('WISH_LANGSMITH_ENABLED','1')
    monkeypatch.setenv('LANGSMITH_API_KEY','synthetic-test-key')
    monkeypatch.setenv('WISH_AGENT_ENABLED','1')
    monkeypatch.setenv('WISH_KEYWORD_ONLY','1')
    monkeypatch.setenv('WISH_MANIFEST','data/manifest.example.json')
    monkeypatch.setattr(telemetry,'Client',FailingClient)
    monkeypatch.setattr(main,'build_model',lambda *args,**kwargs:model)
    with TestClient(main.app) as client:
        main.app.state.agent.log_path=tmp_path/'agent.jsonl'
        assert client.get('/ready').json()['stage']=='agent_json'
        response=client.post('/api/search',json={'query':'RIKU chose RIKU'})
        assert response.status_code==200 and response.json()['status']=='found'
        publisher=main.app.state.agent.telemetry
        assert not publisher.enabled and publisher.client is None and publisher.task is None
    assert model.closed and main.app.state.agent is None


@pytest.mark.parametrize('same_query,budget', [(True,0),(False,10_000)])
def test_stopped_replan_does_not_announce_another_attempt(tmp_path,same_query,budget):
    agent,session=make_agent(tmp_path,ScriptedModel(('uncertain',),same_query=same_query),
                             min_replan_budget=budget)
    events=[]
    async def progress(event,payload): events.append((event,payload))
    response,_=asyncio.run(agent.run('장면',progress=progress))
    assert response.search_attempts == len(session.queries) == 1
    assert not any(event=='replanning' for event,_ in events)
    assert [payload['attempt'] for event,payload in events if event=='searching']==[0]


class SlowRewriteModel(ScriptedModel):
    async def rewrite(self, query, previous, feedback):
        await asyncio.sleep(0.3)
        return await super().rewrite(query, previous, feedback)


def test_progress_stage_ms_attributes_rewrite_time_to_replanning(tmp_path):
    agent,_=make_agent(tmp_path,SlowRewriteModel(('irrelevant','relevant')))
    events=[]
    async def progress(event,payload): events.append((event,payload))
    _,record=asyncio.run(agent.run('장면',progress=progress))
    names=[event for event,_ in events]
    assert names==['routing','searching','validating','replanning','searching','validating']
    replanning=dict(events)['replanning']['stage_ms']
    assert replanning['replan']>=250
    # The slow rewrite must not leak into the validating work reported on the same event.
    assert replanning.get('context',0)+replanning.get('verification',0)<250
    assert events[0][1]['stage_ms']=={} and set(events[1][1]['stage_ms'])=={'router'}
    # The next searching event does not repeat the rewrite time.
    assert 'replan' not in events[4][1]['stage_ms']
    assert {'context','verification','finalize'} <= set(record['stage_tail_ms'])


def test_trace_is_off_by_default_and_records_rounds_when_enabled(tmp_path):
    agent,_=make_agent(tmp_path,ScriptedModel(('irrelevant','relevant')))
    asyncio.run(agent.run('장면'))
    assert not (tmp_path/'traces').exists()
    agent,_=make_agent(tmp_path,ScriptedModel(('irrelevant','relevant')),trace_dir=tmp_path/'traces')
    response,_=asyncio.run(agent.run('장면'))
    [path]=list((tmp_path/'traces').glob('*.json'))
    trace=json.loads(path.read_text())
    steps=[t['step'] for t in trace['trace']]
    assert steps==['router','search','context','verification','replan','search','context','verification']
    first_search=trace['trace'][1]
    assert first_search['attempt']==0 and first_search['candidates'][0]['rank']==1
    assert trace['user_query']=='장면' and trace['status']==response.status=='found'
    assert trace['trace'][3]['verdicts'][0]['verdict']=='irrelevant'


def test_trace_dir_must_be_private():
    from backend.app.main import trace_dir
    from backend.app.services.video_catalog import ROOT
    assert trace_dir(None) is None
    assert trace_dir('/tmp/public-traces') is None
    assert trace_dir('eval/private/traces')==(ROOT/'eval/private/traces').resolve()
