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


def test_asgi_disconnect_before_iterator_start_releases_reservation(monkeypatch):
    import backend.app.main as main
    from backend.app.schemas import SearchRequest
    async def run():
        monkeypatch.setattr(main.app.state, 'session', object(), raising=False)
        monkeypatch.setattr(main.app.state, 'busy', False, raising=False)
        response = await main.search_stream(SearchRequest(query='장면'))
        assert main.app.state.busy
        async def receive(): return {'type': 'http.disconnect'}
        async def send(message):
            # Force disconnect to win before first iterator access.
            await asyncio.sleep(.01)
        await response({'type':'http', 'asgi':{'spec_version':'2.3'}}, receive, send)
        assert response.owner.task is None and not main.app.state.busy
    asyncio.run(run())


def test_asgi_disconnect_waits_for_cleanup_and_timeout_keeps_busy(monkeypatch):
    import backend.app.main as main
    from backend.app.schemas import SearchRequest, SearchResponse
    from backend.app.sse import StreamOwner
    async def run(timeout):
        entered, cleaning, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()
        tasks = set()
        class SlowAgent:
            async def run(self, query, *, request_id, progress):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaning.set()
                    await finish.wait()
        monkeypatch.setattr(main.app.state, 'session', object(), raising=False)
        monkeypatch.setattr(main.app.state, 'agent', SlowAgent(), raising=False)
        monkeypatch.setattr(main.app.state, 'busy', False, raising=False)
        monkeypatch.setattr(main.app.state, 'search_tasks', tasks, raising=False)
        monkeypatch.setattr(StreamOwner, 'cleanup_timeout', timeout)
        response = await main.search_stream(SearchRequest(query='장면'))
        async def receive():
            await entered.wait()
            return {'type':'http.disconnect'}
        async def send(message): pass
        request = asyncio.create_task(response(
            {'type':'http', 'asgi':{'spec_version':'2.3'}}, receive, send))
        await cleaning.wait()
        assert main.app.state.busy
        from fastapi import HTTPException
        try:
            await main.search(SearchRequest(query='다음 검색'))
        except HTTPException as exc:
            assert exc.status_code == 503
        else:
            raise AssertionError('overlapping search accepted')
        if timeout < 1:
            await asyncio.wait_for(request, 1)
            assert main.app.state.busy and tasks
        finish.set()
        await request
        for _ in range(10):
            if not main.app.state.busy: break
            await asyncio.sleep(0)
        assert not main.app.state.busy and not tasks
        class NextAgent:
            async def run(self, query, *, request_id):
                return SearchResponse(request_id=request_id, status='not_found',
                    search_attempts=1, results=[], warnings=[]), {}
        main.app.state.agent = NextAgent()
        assert (await main.search(SearchRequest(query='다음 검색'))).status == 'not_found'
    asyncio.run(run(5))
    asyncio.run(run(.01))


def test_send_failure_before_body_start_releases_busy():
    from backend.app.sse import ManagedStreamingResponse, StreamOwner
    async def run():
        released = []
        async def body(): yield 'unused'
        async def receive(): return {'type':'http.disconnect'}
        async def send(message): raise OSError('connection lost')
        response = ManagedStreamingResponse(body(), owner=StreamOwner(lambda:released.append(True)))
        try:
            await response({'type':'http', 'asgi':{'spec_version':'2.4'}}, receive, send)
        except Exception:
            pass
        assert released == [True]
    asyncio.run(run())


def test_baseline_progress_tracks_tool_boundary(monkeypatch):
    import backend.app.main as main
    from backend.app.services.search import call_tool, search_and_verify
    from backend.tests.test_search_service import FakeSession
    async def run():
        session = FakeSession('normal')
        v = session.catalog.videos['SYNTHETIC01']
        from backend.app.schemas import MetadataReply
        metadata = {v.video_id: MetadataReply(video_id=v.video_id, title=v.title,
            url=v.url, title_verified=False, timing_verified=True)}
        events = []
        async def tool(*args):
            events.append(args[1])
            return await call_tool(*args)
        async def progress(event, payload): events.append(event)
        await search_and_verify(session, 'RIKU chose RIKU', 'keyword', metadata,
            tool_call=tool, progress=progress)
        assert events[:4] == ['searching','search_transcripts','validating','get_scene_context']
    asyncio.run(run())


def test_json_and_sse_unexpected_failure_have_same_safe_code(monkeypatch):
    import backend.app.main as main
    model = ScriptedModel()
    async def fail(*args, **kwargs): raise RuntimeError('private details')
    configure(monkeypatch, main, model)
    with TestClient(main.app) as client:
        monkeypatch.setattr(main.app.state.agent, 'run', fail)
        response = client.post('/api/search', json={'query':'장면'})
        assert response.status_code == 503
        events = parse_events(client.post('/api/search/stream', json={'query':'장면'}).text)
        assert events[0][0] == 'error'
        assert response.json()['detail'] == events[0][1] | {'request_id':response.json()['detail']['request_id']}
        assert events[0][1]['code'] == 'agent_failure'
        assert 'private details' not in response.text + str(events)


def test_disconnect_with_full_progress_queue_finishes_cleanup(monkeypatch):
    import backend.app.main as main
    from backend.app.schemas import SearchRequest
    async def run():
        started, cancelled = asyncio.Event(), asyncio.Event()
        class FloodAgent:
            async def run(self, query, *, request_id, progress):
                started.set()
                try:
                    for _ in range(100):
                        await progress('searching', {'attempt':0})
                finally:
                    cancelled.set()
        monkeypatch.setattr(main.app.state, 'session', object(), raising=False)
        monkeypatch.setattr(main.app.state, 'agent', FloodAgent(), raising=False)
        monkeypatch.setattr(main.app.state, 'busy', False, raising=False)
        response = await main.search_stream(SearchRequest(query='장면'))
        async def receive():
            await started.wait()
            return {'type':'http.disconnect'}
        async def send(message):
            if message['type'] == 'http.response.body':
                await asyncio.Event().wait()
        await asyncio.wait_for(response(
            {'type':'http', 'asgi':{'spec_version':'2.3'}}, receive, send), 1)
        assert cancelled.is_set() and not main.app.state.busy
    asyncio.run(run())


def test_lifespan_drains_search_tasks_before_mcp_close(monkeypatch):
    from contextlib import asynccontextmanager
    import backend.app.main as main
    from backend.tests.test_search_service import FakeSession
    started, finished = asyncio.Event(), asyncio.Event()
    @asynccontextmanager
    async def connect(**kwargs):
        try:
            yield FakeSession('normal')
        finally:
            assert finished.is_set()
    async def pending():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(.01)
            finished.set()
    monkeypatch.setattr(main, 'connect', connect)
    monkeypatch.setenv('WISH_MANIFEST', 'data/manifest.example.json')
    monkeypatch.delenv('WISH_AGENT_ENABLED', raising=False)
    async def run():
        async with main.lifespan(main.app):
            task = asyncio.create_task(pending())
            main.app.state.search_tasks.add(task)
            await started.wait()
        assert task.done() and finished.is_set()
    asyncio.run(run())
