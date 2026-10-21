"""POST SSE integration tests with a real stdio MCP and scripted model."""

import asyncio
import json

from fastapi.testclient import TestClient

from backend.tests.test_agent import ScriptedModel
from backend.app.services.search import SearchFailure


def parse_events(text):
    events=[]
    for frame in text.strip().split('\n\n'):
        lines=frame.splitlines()
        event=next(line[7:] for line in lines if line.startswith('event: '))
        data='\n'.join(line[6:] for line in lines if line.startswith('data: '))
        events.append((event,json.loads(data)))
    return events


def configure(monkeypatch, main, model):
    monkeypatch.setenv('WISH_AGENT_ENABLED','1')
    monkeypatch.setenv('WISH_KEYWORD_ONLY','1')
    monkeypatch.setenv('WISH_MANIFEST','data/manifest.example.json')
    monkeypatch.setattr(main,'OllamaModel',lambda *args:model)


def test_agent_sse_orders_progress_before_validated_result(monkeypatch,tmp_path):
    import backend.app.main as main
    model=ScriptedModel()
    configure(monkeypatch,main,model)
    with TestClient(main.app) as client:
        main.app.state.agent.log_path=tmp_path/'agent.jsonl'
        response=client.post('/api/search/stream',json={'query':'RIKU chose RIKU'})
        assert response.status_code==200
        assert response.headers['content-type'].startswith('text/event-stream')
        events=parse_events(response.text)
        names=[name for name,_ in events]
        assert names==['routing','searching','validating','result','done']
        request_ids={data['request_id'] for _,data in events}
        assert len(request_ids)==1
        result=events[-2][1]
        assert result['status']=='found' and result['results'][0]['speaker'] is None
        assert result['results'][0]['url'].endswith('&t=3s')
        assert not main.app.state.busy


def test_agent_sse_replanning_attempts_are_bounded(monkeypatch,tmp_path):
    import backend.app.main as main
    model=ScriptedModel(('irrelevant','irrelevant','relevant'))
    configure(monkeypatch,main,model)
    with TestClient(main.app) as client:
        main.app.state.agent.log_path=tmp_path/'agent.jsonl'
        events=parse_events(client.post('/api/search/stream',json={'query':'장면'}).text)
        replans=[data['attempt'] for name,data in events if name=='replanning']
        searches=[data['attempt'] for name,data in events if name=='searching']
        assert replans==[1,2] and searches==[0,1,2]
        assert [name for name,_ in events][-2:]==['result','done']


def test_stream_failure_emits_safe_error_then_done(monkeypatch,tmp_path):
    import backend.app.main as main
    model=ScriptedModel()
    async def fail(*args): raise SearchFailure('model_unavailable')
    model.route=fail
    configure(monkeypatch,main,model)
    with TestClient(main.app) as client:
        main.app.state.agent.log_path=tmp_path/'agent.jsonl'
        events=parse_events(client.post('/api/search/stream',json={'query':'장면'}).text)
        assert [name for name,_ in events]==['routing','error','done']
        assert events[1][1]['code']=='model_unavailable'
        assert '의미 검증 모델' in events[1][1]['message']
        assert events[2][1]['status']=='error'
        assert not main.app.state.busy


def test_stream_preflight_errors_remain_http_errors(monkeypatch):
    import backend.app.main as main
    monkeypatch.setenv('WISH_MANIFEST','data/manifest.example.json')
    monkeypatch.delenv('WISH_AGENT_ENABLED',raising=False)
    with TestClient(main.app) as client:
        assert client.post('/api/search/stream',json={'query':'  '}).status_code==422
        main.app.state.busy=True
        response=client.post('/api/search/stream',json={'query':'장면'})
        assert response.status_code==503
        main.app.state.busy=False


def test_closing_stream_cancels_agent_and_releases_busy():
    import backend.app.main as main
    from backend.app.schemas import SearchRequest
    cancelled=asyncio.Event()
    class SlowAgent:
        async def run(self,query,*,request_id,progress):
            await progress('routing',{'attempt':0})
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
    async def run():
        previous={name:getattr(main.app.state,name,None) for name in ('session','agent','busy')}
        main.app.state.session=object();main.app.state.agent=SlowAgent();main.app.state.busy=False
        try:
            response=await main.search_stream(SearchRequest(query='장면'))
            iterator=response.body_iterator
            first=await anext(iterator)
            assert first.startswith('event: routing\n')
            await iterator.aclose()
            assert cancelled.is_set() and not main.app.state.busy
        finally:
            for name,value in previous.items(): setattr(main.app.state,name,value)
    asyncio.run(run())
