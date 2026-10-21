"""Swappable LLM backends: same contract, no network or billing (httpx.MockTransport)."""

import asyncio
import json

import httpx
import pytest

from backend.app.agent.model import OllamaModel, Route, Verification, build_model
from backend.app.agent.openai_model import OpenAIModel, strict_schema
from backend.app.services.search import SearchFailure

EVIDENCE = [{'evidence_id': 'V:1', 'quote': 'synthetic', 'caption_type': 'unknown', 'context': []}]


async def openai_with(handler, **kwargs):
    model = OpenAIModel(api_key='sk-test-not-real', **kwargs)
    await model.client.aclose()
    model.client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     base_url='https://api.test/v1',
                                     headers={'Authorization': 'Bearer sk-test-not-real'})
    return model


def completion(content, prompt_tokens=11, completion_tokens=7):
    return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(content)}}],
                                     'usage': {'prompt_tokens': prompt_tokens,
                                               'completion_tokens': completion_tokens}})


def test_factory_selects_backend_from_one_env_var():
    ollama = build_model({})
    assert isinstance(ollama, OllamaModel) and ollama.name == 'ollama:qwen3:8b'
    legacy = build_model({'WISH_LLM_MODEL': 'qwen3:4b'})
    assert legacy.model == legacy.quality_model == 'qwen3:4b'
    openai = build_model({'WISH_LLM_BACKEND': 'openai', 'OPENAI_API_KEY': 'k'})
    assert isinstance(openai, OpenAIModel) and openai.name == 'openai:gpt-4o-mini/gpt-4o'
    custom = build_model({'WISH_LLM_BACKEND': 'OpenAI', 'OPENAI_FAST_MODEL': 'f',
                          'OPENAI_QUALITY_MODEL': 'q'})
    assert (custom.model, custom.quality_model) == ('f', 'q')
    for model in (ollama, legacy, openai, custom):
        asyncio.run(model.close())
    with pytest.raises(ValueError):
        build_model({'WISH_LLM_BACKEND': 'other'})


def test_openai_uses_fast_and_quality_models_with_strict_schema_and_counts_tokens():
    sent = []
    def handle(request):
        body = json.loads(request.content)
        sent.append(body)
        assert request.headers['Authorization'] == 'Bearer sk-test-not-real'
        name = body['response_format']['json_schema']['name']
        if name == 'Route':
            return completion({'intent': 'scene_search', 'search_query': 'RIKU chose RIKU'})
        if name == 'Verification':
            return completion({'judgments': [{'evidence_id': 'V:1', 'verdict': 'relevant'}]})
        return completion({'search_query': 'RIKU picked himself'})
    async def run():
        model = await openai_with(handle)
        try:
            route = await model.route('장면')
            verdict = await model.verify('장면', EVIDENCE)
            rewrite = await model.rewrite('장면', ['RIKU chose RIKU'], {'V:1': 'irrelevant'})
            return route, verdict, rewrite, dict(model.usage)
        finally:
            await model.close()
    route, verdict, rewrite, usage = asyncio.run(run())
    assert route.search_query == 'RIKU chose RIKU' and verdict.judgments[0].verdict == 'relevant'
    assert rewrite == 'RIKU picked himself'
    assert [body['model'] for body in sent] == ['gpt-4o-mini', 'gpt-4o', 'gpt-4o-mini']
    fmt = sent[1]['response_format']
    assert fmt['type'] == 'json_schema' and fmt['json_schema']['strict'] is True
    assert sent[0]['temperature'] == 0 and sent[0]['messages'][0]['role'] == 'system'
    assert usage == {'calls': 3, 'tokens_in': 33, 'tokens_out': 21}


def test_strict_schema_keeps_shape_but_drops_unsupported_keywords():
    schema = strict_schema(Verification)
    text = json.dumps(schema)
    assert 'maxItems' not in text and 'minLength' not in text
    assert schema['additionalProperties'] is False and schema['required'] == ['judgments']
    assert strict_schema(Route)['properties']['intent']['enum']


@pytest.mark.parametrize('failure,code', [
    ('timeout', 'model_timeout'), ('401', 'model_unavailable'),
    ('not_json', 'model_invalid_response'), ('wrong_shape', 'model_invalid_response'),
    ('refusal', 'model_invalid_response'),
])
def test_openai_errors_are_typed_and_hide_private_text(failure, code):
    def handle(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('private text', request=request)
        if failure == '401':
            return httpx.Response(401, json={'error': {'message': 'private key detail'}})
        if failure == 'not_json':
            return httpx.Response(200, json={'choices': [{'message': {'content': 'private not json'}}]})
        if failure == 'refusal':
            return httpx.Response(200, json={'choices': [{'message': {'content': None, 'refusal': 'no'}}]})
        return completion({'intent': 'not-a-real-intent', 'search_query': 'x'})
    async def run():
        model = await openai_with(handle)
        try:
            with pytest.raises(SearchFailure) as exc:
                await model.route('장면')
            return exc.value
        finally:
            await model.close()
    error = asyncio.run(run())
    assert error.code == code and 'private' not in str(error)


def test_openai_ready_requires_key_and_accessible_models():
    async def run(key, status):
        model = await openai_with(lambda request: httpx.Response(status, json={'id': 'm'}))
        model.api_key = key
        try:
            await model.ready()
        finally:
            await model.close()
    with pytest.raises(SearchFailure) as missing:
        asyncio.run(run('', 200))
    assert missing.value.code == 'model_unavailable'
    with pytest.raises(SearchFailure) as unknown:
        asyncio.run(run('sk-test', 404))
    assert unknown.value.code == 'model_not_installed'
    asyncio.run(run('sk-test', 200))


def test_ollama_routes_roles_to_models_and_counts_tokens():
    sent = []
    def handle(request):
        body = json.loads(request.content)
        sent.append(body['model'])
        content = ({'judgments': [{'evidence_id': 'V:1', 'verdict': 'uncertain'}]}
                   if 'judgments' in json.dumps(body['format']) else
                   {'intent': 'scene_search', 'search_query': 'q'})
        return httpx.Response(200, json={'message': {'content': json.dumps(content)},
                                         'prompt_eval_count': 5, 'eval_count': 2})
    async def run():
        model = OllamaModel('fast-local', 'quality-local')
        await model.client.aclose()
        model.client = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url='http://local')
        try:
            await model.route('장면')
            await model.verify('장면', EVIDENCE)
            return dict(model.usage)
        finally:
            await model.close()
    usage = asyncio.run(run())
    assert sent == ['fast-local', 'quality-local']
    assert usage == {'calls': 2, 'tokens_in': 10, 'tokens_out': 4}


class _CapturingSession:
    """Stands in for requests.Session so LangSmith traces are captured, never sent."""
    def __init__(self):
        self.posted = []
    def request(self, method, url, **kwargs):
        payload = kwargs.get('data') or kwargs.get('json')
        self.posted.append(json.loads(payload) if isinstance(payload, (bytes, str)) else payload)
        class Response:
            status_code, text, content, headers = 200, '{}', b'{}', {}
            def json(self): return {}
            def raise_for_status(self): pass
        return Response()
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _traced_agent_run(tmp_path, enabled):
    import langsmith
    from backend.tests.test_agent import make_agent
    def handle(request):
        body = json.loads(request.content)
        schema = json.dumps(body['format'])
        if 'judgments' in schema:
            ids = [part.split('"')[0] for part in body['messages'][1]['content'].split('"evidence_id": "')[1:]]
            content = {'judgments': [{'evidence_id': i, 'verdict': 'relevant'} for i in ids]}
        else:
            content = {'intent': 'scene_search', 'search_query': 'RIKU chose RIKU'}
        return httpx.Response(200, json={'message': {'content': json.dumps(content)},
                                         'prompt_eval_count': 9, 'eval_count': 4})
    session = _CapturingSession()
    client = langsmith.Client(api_url='http://ls.test', api_key='test-key', session=session,
                              auto_batch_tracing=False)
    class Telemetry:
        def __init__(self): self.enabled, self.client = enabled, client
        def submit(self, record): pass
    async def run():
        model = OllamaModel()
        await model.client.aclose()
        model.client = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url='http://local')
        agent, _ = make_agent(tmp_path, model, telemetry=Telemetry())
        try:
            return await agent.run('장면')
        finally:
            await model.close()
    response, _ = asyncio.run(run())
    client.flush()
    runs = {}
    for payload in session.posted:
        runs.setdefault(payload['id'], {}).update({k: v for k, v in payload.items() if v is not None})
    return response, list(runs.values())


def test_langsmith_traces_every_llm_call_only_when_opted_in(tmp_path):
    response, runs = _traced_agent_run(tmp_path, enabled=False)
    assert response.status == 'found' and runs == []
    response, runs = _traced_agent_run(tmp_path, enabled=True)
    assert response.status == 'found'
    llm = [run for run in runs if run.get('run_type') == 'llm']
    assert sorted(run['name'] for run in llm) == ['ollama.Route', 'ollama.Verification']
    for run in llm:
        assert run['extra']['metadata']['ls_model_name'] == 'qwen3:8b'
        assert run['extra']['metadata']['ls_provider'] == 'ollama'
        assert run['extra']['metadata']['usage_metadata']['total_tokens'] == 13
        assert run['inputs']['messages'][1]['role'] == 'user'
    root = next(run for run in runs if run.get('name') == 'LangGraph')
    assert root['extra']['metadata']['llm_backend'] == 'ollama:qwen3:8b'
    assert {'router', 'search', 'context', 'verification', 'finalize'} <= {run.get('name') for run in runs}
    ids = {run['id'] for run in runs}
    assert all(run.get('parent_run_id') in ids for run in llm)


def test_route_allows_blank_query_only_for_intents_that_do_not_search():
    from pydantic import ValidationError
    for intent in ('unsupported', 'chat'):
        assert Route(intent=intent, search_query='').search_query == ''
    for intent in ('scene_search', 'speaker_query'):
        with pytest.raises(ValidationError):
            Route(intent=intent, search_query='   ')
    assert strict_schema(Route)['required'] == ['intent', 'search_query']  # still required by the API


@pytest.mark.parametrize('intent,expected', [('unsupported', 'unsupported'), ('chat', 'unsupported')])
def test_blank_query_for_unsupported_requests_ends_as_unsupported_not_an_error(tmp_path, intent, expected):
    from backend.tests.test_agent import make_agent
    def handle(request):
        return completion({'intent': intent, 'search_query': ''})
    async def run():
        model = await openai_with(handle)
        agent, session = make_agent(tmp_path, model)
        try:
            return await agent.run('리쿠가 입은 옷 색깔은 뭐야?'), session, model
        finally:
            await model.close()
    (response, _), session, model = asyncio.run(run())
    assert response.status == expected and response.results == [] and not session.queries
    assert 'subtitle_only_scope' in response.warnings


def test_blank_query_for_a_searchable_intent_is_still_a_model_failure():
    def handle(request):
        return completion({'intent': 'scene_search', 'search_query': ''})
    async def run():
        model = await openai_with(handle)
        try:
            with pytest.raises(SearchFailure) as exc:
                await model.route('장면')
            return exc.value.code
        finally:
            await model.close()
    assert asyncio.run(run()) == 'model_invalid_response'


def test_route_keeps_the_user_question_as_placeholder_when_blank_and_not_searching():
    def handle(request):
        return completion({'intent': 'unsupported', 'search_query': ''})
    async def run():
        model = await openai_with(handle)
        try:
            return await model.route('리쿠가 입은 옷 색깔은 뭐야?')
        finally:
            await model.close()
    decision = asyncio.run(run())
    assert decision.intent == 'unsupported' and decision.search_query == '리쿠가 입은 옷 색깔은 뭐야?'
