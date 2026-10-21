"""Role-separated nodes, bounded replanning, no free-form source generation."""

import asyncio
import json
import logging
from pathlib import Path
import time
from typing import Awaitable, Callable, Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from backend.app.schemas import ContextReply, SceneResult, SearchReply, SearchRequest, SearchResponse
from backend.app.services.search import (SearchFailure, call_tool, evidence_key,
                                         ground_candidates, timing_warning)
from backend.app.services.video_catalog import ROOT

MAX_REPLAN_ROUNDS = 2
MIN_REPLAN_BUDGET_SECONDS = 25
logger = logging.getLogger('wish_finder.agent')


class FinderState(TypedDict, total=False):
    request_id: str
    user_query: str
    intent: Literal['scene_search', 'speaker_query', 'unsupported', 'chat']
    query: str
    queries: list[str]
    attempt: int
    reply: SearchReply
    grounded: list[SceneResult]
    contexts: dict[str, ContextReply]
    relevant: list[SceneResult]
    uncertain: list[SceneResult]
    verdicts: dict[str, str]
    warnings: list[str]
    stop_replan: bool
    can_replan: bool
    deadline: float
    round_all_rejected: bool
    timing: dict[str, str]
    response: SearchResponse


class RunStats:
    def __init__(self, progress=None):
        self.tool_calls = 0
        self.llm_calls = 0
        self.search_attempts = 0
        self.stages = []
        self.latest_grounded = []
        self.best_uncertain = []
        self.timing = {}
        self.intent = None
        self.progress = progress


class FinderAgent:
    """Compile once per lifespan; dependencies are reused, State stays per request."""
    def __init__(self, session, metadata, model, *, mode='hybrid',
                 tool_call=call_tool, timeout=60, log_path=None, telemetry=None,
                 min_replan_budget=MIN_REPLAN_BUDGET_SECONDS):
        self.session, self.metadata, self.model = session, metadata, model
        self.mode, self.tool_call, self.timeout = mode, tool_call, timeout
        self.log_path = Path(log_path) if log_path else ROOT/'logs/agent.jsonl'
        self.telemetry = telemetry
        self.min_replan_budget = min_replan_budget
        graph = StateGraph(FinderState)
        for name in ['router','search','context','verification','replan','finalize']:
            graph.add_node(name, self._node(name))
        graph.add_edge(START,'router')
        graph.add_conditional_edges('router',lambda s: 'finalize' if s['intent'] in
                                    {'unsupported','chat'} else 'search')
        graph.add_edge('search','context')
        graph.add_edge('context','verification')
        graph.add_conditional_edges('verification',self._after_verification)
        graph.add_conditional_edges('replan',lambda s: 'finalize' if s.get('stop_replan') else 'search')
        graph.add_edge('finalize',END)
        self.graph = graph.compile()

    def _node(self, name):
        async def run(state, config):
            stats = config['configurable']['stats']
            started = time.monotonic()
            try:
                event = {'router':'routing','search':'searching','context':'validating',
                         'replan':'replanning'}.get(name)
                if event and stats.progress is not None:
                    attempt = state.get('attempt',0)+(1 if name=='replan' else 0)
                    await stats.progress(event,{'attempt':attempt})
                return await getattr(self, '_'+name)(state, stats)
            finally:
                stats.stages.append({'node':name,'attempt':state.get('attempt',0),
                                     'seconds':round(time.monotonic()-started,4)})
        return run

    async def _llm(self, stats, method, *args):
        stats.llm_calls += 1
        try:
            async with asyncio.timeout(20):
                return await getattr(self.model,method)(*args)
        except TimeoutError as exc:
            raise SearchFailure('model_timeout') from exc

    async def _tool(self, stats, name, arguments, schema):
        stats.tool_calls += 1
        return await self.tool_call(self.session,name,arguments,schema)

    async def _router(self, state, stats):
        route = await self._llm(stats,'route',state['user_query'])
        stats.intent = route.intent
        query = SearchRequest(query=route.search_query).query
        return {'intent':route.intent,'query':query,'queries':[query]}

    async def _search(self, state, stats):
        stats.search_attempts += 1
        reply = await self._tool(stats,'search_transcripts',
            {'query':state['query'],'mode':self.mode,'top_k':3},SearchReply)
        return {'reply':reply}

    async def _context(self, state, stats):
        async def counted(name, arguments, schema):
            return await self._tool(stats,name,arguments,schema)
        results, _, timing, contexts = await ground_candidates(state['reply'],self.metadata,counted)
        stats.latest_grounded = results
        stats.timing.update(timing)
        return {'grounded':results,'contexts':contexts,'timing':{**state.get('timing',{}),**timing},
                'round_all_rejected':bool(state['reply'].candidates) and not results}

    async def _verification(self, state, stats):
        # Do not send invalid/ungrounded candidates to the semantic model.
        if not state['grounded']:
            can_replan = (state['attempt'] < MAX_REPLAN_ROUNDS and
                          state['deadline']-time.monotonic() >= self.min_replan_budget)
            warnings = list(state['warnings'])
            if state['attempt'] < MAX_REPLAN_ROUNDS and not can_replan:
                warnings.append('replan_budget_exhausted')
            return {'verdicts':{},'relevant':[],'uncertain':state.get('uncertain',[]),
                    'can_replan':can_replan,'warnings':list(dict.fromkeys(warnings))}
        evidence = []
        for r in state['grounded']:
            context = state['contexts'][evidence_key(r)]
            evidence.append({'evidence_id':evidence_key(r),'quote':r.evidence_text,
                'caption_type':r.evidence_type,
                'context':[{'cue_id':c.cue_id,'text':c.original_text} for c in context.cues]})
        decision = await self._llm(stats,'verify',state['user_query'],evidence)
        expected = {evidence_key(r) for r in state['grounded']}
        ids = [j.evidence_id for j in decision.judgments]
        if len(ids)!=len(set(ids)) or set(ids)!=expected:
            raise SearchFailure('model_invalid_evidence_ids')
        verdicts = {j.evidence_id:j.verdict for j in decision.judgments}
        # A complete verdict set ends the unjudged-candidate lifecycle. Only a
        # verification failure may expose latest_grounded as a partial result.
        stats.latest_grounded = []
        uncertain = {evidence_key(r):r for r in state.get('uncertain',[])}
        for r in state['grounded']:
            if verdicts[evidence_key(r)]=='uncertain':
                uncertain[evidence_key(r)] = r
            else:
                uncertain.pop(evidence_key(r),None)
        relevant = [r for r in state['grounded'] if verdicts[evidence_key(r)]=='relevant']
        uncertain_results = list(uncertain.values())[:3]
        stats.best_uncertain = uncertain_results
        can_replan = (not relevant and state['attempt'] < MAX_REPLAN_ROUNDS and
                      state['deadline']-time.monotonic() >= self.min_replan_budget)
        warnings = list(state['warnings'])
        if not relevant and state['attempt'] < MAX_REPLAN_ROUNDS and not can_replan:
            warnings.append('replan_budget_exhausted')
        return {'verdicts':verdicts,
                'relevant':relevant,'uncertain':uncertain_results,
                'can_replan':can_replan,'warnings':list(dict.fromkeys(warnings))}

    def _after_verification(self, state):
        return 'replan' if state.get('can_replan') else 'finalize'

    async def _replan(self, state, stats):
        query = await self._llm(stats,'rewrite',state['user_query'],state['queries'],state['verdicts'])
        query = SearchRequest(query=query).query
        if state['deadline']-time.monotonic() < self.min_replan_budget:
            return {'stop_replan':True,'warnings':list(dict.fromkeys(
                [*state['warnings'],'replan_budget_exhausted']))}
        if query.casefold() in {x.casefold() for x in state['queries']}:
            return {'stop_replan':True,'warnings':[*state['warnings'],'replan_query_unchanged']}
        return {'query':query,'queries':[*state['queries'],query],'attempt':state['attempt']+1}

    async def _finalize(self, state, stats):
        warnings = list(state['warnings'])
        if state['intent'] in {'unsupported','chat'}:
            results, status = [], 'unsupported'
            warnings.append('subtitle_only_scope')
        else:
            results = state.get('relevant',[]) or state.get('uncertain',[])
            status = ('found' if state.get('relevant') else 'ambiguous') if results else (
                'unsupported' if state.get('round_all_rejected') else 'not_found')
            if state.get('round_all_rejected'):
                warnings.append('evidence_rejected')
            if status=='ambiguous':
                warnings.append('semantic_uncertain')
        if state['intent']=='speaker_query':
            warnings.append('speaker_unknown')
        safe_results = []
        for r in results:
            explanation = ('원문 자막의 문맥이 질문의 장면과 관련 있다고 판정했습니다.'
                           if status=='found' else '관련 가능성이 있지만 장면 일치를 확정할 수 없습니다.')
            if state['intent']=='speaker_query':
                explanation += ' 자막만으로 화자를 확인할 수 없습니다.'
            safe_results.append(r.model_copy(update={'explanation_ko':explanation}))
            warning = timing_warning(state.get('timing',{}).get(r.video_id,
                'sampled' if self.metadata[r.video_id].timing_verified else 'unverified'))
            if warning not in warnings:
                warnings.append(warning)
        # Every result remains unknown even for scene questions.
        if safe_results and 'speaker_unknown' not in warnings:
            warnings.append('speaker_unknown')
        response = SearchResponse(request_id=state['request_id'],status=status,
            search_attempts=stats.search_attempts,results=safe_results,warnings=warnings)
        return {'response':response}

    def _fallback(self, request_id, stats, warning, *, ambiguous=False):
        results = stats.best_uncertain if ambiguous else stats.latest_grounded
        if not results:
            return None
        warnings = [warning]
        status = 'ambiguous' if ambiguous else 'partial'
        if ambiguous:
            warnings.append('semantic_uncertain')
        else:
            warnings.append('semantic_verification_skipped')
        if stats.intent == 'speaker_query' or results:
            warnings.append('speaker_unknown')
        safe = []
        for result in results[:3]:
            explanation = ('관련 가능성이 있지만 장면 일치를 확정할 수 없습니다.' if ambiguous else
                           '원문은 확인했지만 의미 검증 모델 오류로 장면 일치를 확정하지 못했습니다.')
            if stats.intent == 'speaker_query':
                explanation += ' 자막만으로 화자를 확인할 수 없습니다.'
            safe.append(result.model_copy(update={'explanation_ko':explanation}))
            warnings.append(timing_warning(stats.timing[result.video_id]))
        return SearchResponse(request_id=request_id,status=status,search_attempts=stats.search_attempts,
                              results=safe,warnings=list(dict.fromkeys(warnings)))

    def _emit(self, request_id, stats, started, state, error):
        record = self._telemetry(request_id,stats,started,state,error)
        try:
            self.log_path.parent.mkdir(parents=True,exist_ok=True)
            with self.log_path.open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(record,ensure_ascii=False)+'\n')
        except OSError:
            logger.warning('agent_log_failed request_id=%s',request_id)
        if self.telemetry is not None:
            self.telemetry.submit(record)
        return record

    async def run(self, query, *, request_id=None,
                  progress: Callable[[str,dict],Awaitable[None]] | None = None):
        query = SearchRequest(query=query).query
        request_id = request_id or str(uuid4())
        stats = RunStats(progress)
        started = time.monotonic()
        error = None
        state = None
        try:
            # Do not auto-upload raw State/subtitles through ambient LangSmith settings.
            with tracing_context(enabled=False):
                async with asyncio.timeout(self.timeout):
                    state = await self.graph.ainvoke({'request_id':request_id,'user_query':query,
                        'attempt':0,'warnings':[],'timing':{},'deadline':started+self.timeout},
                        config={'configurable':{'stats':stats},'recursion_limit':24})
            record = self._emit(request_id,stats,started,state,None)
            return state['response'], record
        except SearchFailure as exc:
            error = exc.code
            if exc.code.startswith('model_'):
                response = self._fallback(request_id,stats,'semantic_model_error',
                                          ambiguous=bool(stats.best_uncertain))
                if response is not None:
                    state = {'intent':stats.intent,'response':response}
                    record = self._emit(request_id,stats,started,state,exc.code)
                    return response, record
            exc.tool_calls, exc.search_attempts = stats.tool_calls, stats.search_attempts
            self._emit(request_id,stats,started,state,error)
            raise
        except TimeoutError as exc:
            error = 'request_timeout'
            response = self._fallback(request_id,stats,'replan_budget_exhausted',
                                      ambiguous=bool(stats.best_uncertain))
            if response is not None:
                state = {'intent':stats.intent,'response':response}
                record = self._emit(request_id,stats,started,state,error)
                return response, record
            self._emit(request_id,stats,started,state,error)
            raise SearchFailure(error,tool_calls=stats.tool_calls,search_attempts=stats.search_attempts) from exc
        except asyncio.CancelledError:
            error = 'cancelled'
            self._emit(request_id,stats,started,state,error)
            raise
        except Exception as exc:
            error = 'agent_failure'
            self._emit(request_id,stats,started,state,error)
            raise SearchFailure(error,tool_calls=stats.tool_calls,search_attempts=stats.search_attempts) from exc

    @staticmethod
    def _telemetry(request_id, stats, started, state, error):
        return {'request_id':request_id,'intent':state.get('intent') if state else None,
                'status':state['response'].status if state else 'error',
                'search_attempts':stats.search_attempts,'tool_calls':stats.tool_calls,
                'llm_calls':stats.llm_calls,'seconds':round(time.monotonic()-started,4),
                'stages':stats.stages,'error':error}
