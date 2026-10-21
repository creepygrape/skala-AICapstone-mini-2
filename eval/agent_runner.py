"""Final C: run the real FinderAgent; the evaluator never edits Agent behavior.

RouteProbe wraps the model only to (a) capture the Router's first search query so
A/B can reuse it as an identical starting query, and (b) for the control run,
replace that query with a fixed string while still using the model's real intent.
"""

import time
from uuid import uuid4

from backend.app.schemas import SearchRequest, SearchResponse
from backend.app.services.search import SearchFailure
from eval.metrics import agent_metrics, answerability_metrics, scene_metrics


class RouteProbe:
    def __init__(self, inner):
        self.inner, self.override, self.first_query, self.calls = inner, None, None, 0

    @property
    def usage(self):
        return getattr(self.inner, 'usage', None)

    @property
    def name(self):
        return getattr(self.inner, 'name', None)

    def arm(self, override=None):
        self.override, self.first_query, self.calls = override, None, 0
        self.usage_start = dict(self.usage or {})

    def tokens_used(self):
        """Input/output tokens spent since arm(); 0 for models without usage counters."""
        usage, start = self.usage or {}, getattr(self, 'usage_start', {})
        return (usage.get('tokens_in', 0) - start.get('tokens_in', 0),
                usage.get('tokens_out', 0) - start.get('tokens_out', 0))

    async def route(self, query):
        self.calls += 1  # Counted at call start so failed calls keep their cost.
        decision = await self.inner.route(query)
        self.first_query = decision.search_query
        if self.override is not None:
            decision.search_query = SearchRequest(query=self.override).query
        return decision

    async def verify(self, query, evidence):
        self.calls += 1
        return await self.inner.verify(query, evidence)

    async def rewrite(self, query, previous, feedback):
        self.calls += 1
        return await self.inner.rewrite(query, previous, feedback)


async def evaluate_agent_question(agent, probe, question, *, condition, system, override=None):
    """One real Agent execution; failures stay in the measured record."""
    probe.arm(override)
    request_id = str(uuid4())
    start = time.monotonic()
    error, telemetry = None, {}
    try:
        response, telemetry = await agent.run(question.query, request_id=request_id)
    except SearchFailure as exc:
        error = {'code':exc.code, 'fatal':exc.fatal}
        # Agent telemetry is not returned on failure; the probe counted every model call.
        telemetry = {'tool_calls':exc.tool_calls, 'llm_calls':probe.calls,
                     'search_attempts':exc.search_attempts, 'intent':None}
        response = SearchResponse(request_id=request_id, status='error',
                                  search_attempts=exc.search_attempts, results=[], warnings=['search_failed'])
    # Only a fully verified `found` counts as Final C success. partial/ambiguous keep
    # their raw candidate hits in `retrieval_metrics` but never in the success metrics.
    retrieval = scene_metrics(question, response.results)
    scene = retrieval if response.status == 'found' or retrieval is None else {
        'scene_success_at_1':False, 'hit_at_3':False}
    intent = telemetry.get('intent')
    llm_calls = telemetry.get('llm_calls')
    fallback = error is None and bool(telemetry.get('error'))
    return {
        'id':question.id, 'condition':condition, 'system':system, 'query':question.query,
        'initial_query_source':'fixed_override' if override is not None else 'router',
        'router_first_query':probe.first_query, 'answerability':question.answerability,
        'request_id':request_id, 'status':response.status, 'warnings':response.warnings,
        'error':error, 'fallback':fallback, 'telemetry_error':telemetry.get('error'),
        'intent':intent, 'latency_seconds':round(time.monotonic()-start, 6),
        'tool_calls':telemetry.get('tool_calls') or 0, 'llm_calls':llm_calls or 0,
        'llm_tokens_in':probe.tokens_used()[0], 'llm_tokens_out':probe.tokens_used()[1],
        'llm_calls_mismatch':llm_calls is not None and llm_calls != probe.calls,
        'search_rounds':response.search_attempts, 'metrics':scene, 'retrieval_metrics':retrieval,
        'answerability_metrics':answerability_metrics(question, response),
        'agent_metrics':agent_metrics(question, response, intent, scene),
        'results':[{'video_id':x.video_id, 'cue_ids':x.cue_ids, 'start_seconds':x.start_seconds,
                    'speaker':x.speaker, 'speaker_status':x.speaker_status,
                    'explanation_ko':x.explanation_ko} for x in response.results],
    }
