"""Role-separated nodes, bounded replanning, no free-form source generation."""

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import time
from typing import Awaitable, Callable, Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from backend.app.schemas import ContextReply, SceneResult, SearchReply, SearchRequest, SearchResponse
from backend.app.services.search import (SearchFailure, call_tool, evidence_key, fuse_replies,
                                         ground_candidates, timing_warning)
from backend.app.services.video_catalog import ROOT

MAX_REPLAN_ROUNDS = 2
MIN_REPLAN_BUDGET_SECONDS = 25
logger = logging.getLogger('wish_finder.agent')


class FinderState(TypedDict, total=False):
    request_id: str
    user_query: str
    history: list[dict]
    exclude: list[str]
    resolved_query: str
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
    judged: dict[str, str]
    warnings: list[str]
    stop_replan: bool
    can_replan: bool
    deadline: float
    round_all_rejected: bool
    timing: dict[str, str]
    response: SearchResponse


class RunStats:
    def __init__(self, progress=None, trace=False):
        self.tool_calls = 0
        self.llm_calls = 0
        self.search_attempts = 0
        self.stages = []
        self.latest_grounded = []
        self.best_uncertain = []
        self.timing = {}
        self.intent = None
        self.progress = progress
        self.user_query = None
        self.pending = {}
        # Opt-in diagnostic trace (contains subtitle text; written only to a private dir).
        self.trace = [] if trace else None

    def note(self, step, **data):
        if self.trace is not None:
            self.trace.append({'step':step, **data})

    def add_pending(self, node, seconds):
        self.pending[node] = self.pending.get(node, 0) + int(seconds*1000)

    def take_pending(self):
        """Node milliseconds finished since the last public event (reset on read)."""
        pending, self.pending = self.pending, {}
        return pending


class FinderAgent:
    """Compile once per lifespan; dependencies are reused, State stays per request."""
    def __init__(self, session, metadata, model, *, mode='hybrid',
                 tool_call=call_tool, timeout=60, log_path=None, telemetry=None,
                 min_replan_budget=MIN_REPLAN_BUDGET_SECONDS, trace_dir=None, dual_query=False):
        self.session, self.metadata, self.model = session, metadata, model
        # Off by default: first round also searches the user's own words (see _search).
        self.dual_query = dual_query
        self.mode, self.tool_call, self.timeout = mode, tool_call, timeout
        self.log_path = Path(log_path) if log_path else ROOT/'logs/agent.jsonl'
        self.telemetry = telemetry
        self.min_replan_budget = min_replan_budget
        self.trace_dir = Path(trace_dir) if trace_dir else None
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
            reported_live = False
            try:
                event = {'router':'routing','search':'searching','context':'validating'}.get(name)
                if event and stats.progress is not None:
                    attempt = state.get('attempt',0)
                    await stats.progress(event,{'attempt':attempt,'stage_ms':stats.take_pending()})
                update = await getattr(self, '_'+name)(state, stats)
                if name == 'replan' and not update.get('stop_replan') and stats.progress is not None:
                    # Announced after the rewrite finished, so its own time is reported live.
                    stage_ms = stats.take_pending()
                    stage_ms['replan'] = int((time.monotonic()-started)*1000)
                    reported_live = True
                    await stats.progress('replanning', {'attempt': update['attempt'],
                                                        'stage_ms': stage_ms})
                return update
            finally:
                stats.stages.append({'node':name,'attempt':state.get('attempt',0),
                                     'seconds':round(time.monotonic()-started,4)})
                if not reported_live:
                    stats.add_pending(name, time.monotonic()-started)
        return run

    async def _llm(self, stats, method, *args, **kwargs):
        stats.llm_calls += 1
        try:
            async with asyncio.timeout(20):
                return await getattr(self.model,method)(*args, **kwargs)
        except TimeoutError as exc:
            raise SearchFailure('model_timeout') from exc

    async def _tool(self, stats, name, arguments, schema):
        stats.tool_calls += 1
        return await self.tool_call(self.session,name,arguments,schema)

    async def _router(self, state, stats):
        history = state.get('history')
        args = (state['user_query'],history) if history else (state['user_query'],)
        route = await self._llm(stats,'route',*args)
        stats.intent = route.intent
        query = SearchRequest(query=route.search_query).query
        stats.note('router', intent=route.intent, query=query)
        update = {'intent':route.intent,'query':query,'queries':[query]}
        if history and route.intent in {'scene_search','speaker_query'}:
            # The user's question and earlier turns stay immutable. The Router rewrite is only a
            # search aid (and rewrite input); verification gets it as context, never as the criterion.
            update['resolved_query'] = query
        return update

    def _raw_query(self, state):
        """The user's own question as a second first-round query, or None.

        The Router's rewrite can miss translated wording (e.g. "manitto" vs "Secret Santa"),
        while the multilingual dense search often still matches the original Korean.
        Skipped for replans (the rewrite must change the search), follow-ups (the bare question
        is only a pronoun) and when it equals the Router query.
        """
        if not self.dual_query or state.get('attempt',0) != 0 or state.get('resolved_query'):
            return None
        raw = state['user_query']
        return None if raw.casefold() == state['query'].casefold() else raw

    async def _search(self, state, stats):
        stats.search_attempts += 1
        top_k = min(3+len(state.get('exclude',[])),20)
        arguments = {'query':state['query'],'mode':self.mode,'top_k':top_k}
        reply = await self._tool(stats,'search_transcripts',arguments,SearchReply)
        raw, tried = self._raw_query(state), None
        if raw is not None:
            try:
                extra = await self._tool(stats,'search_transcripts',{**arguments,'query':raw},SearchReply)
            except SearchFailure:
                stats.note('search_dual_failed', query=raw)   # the primary search still stands
            else:
                reply = fuse_replies([reply, extra], top_k)
                tried = raw
        if stats.trace is not None:
            stats.note('search', attempt=state.get('attempt',0), query=state['query'], candidates=[
                {'rank':i, 'video_id':c.chunk.video_id, 'start':c.chunk.start_seconds,
                 'end':c.chunk.end_seconds, 'score':round(c.score,5),
                 'selected_cue_id':c.selected_cue_id, 'text':c.chunk.text_for_retrieval[:300]}
                for i,c in enumerate(reply.candidates,1)])
        # A query that was actually searched belongs in the history, so a rewrite cannot repeat it.
        return {'reply':reply,**({'queries':[*state['queries'],tried]} if tried else {})}

    async def _context(self, state, stats):
        async def counted(name, arguments, schema):
            return await self._tool(stats,name,arguments,schema)
        reply = state['reply']
        exclude = set(state.get('exclude',[]))
        shown = False
        if exclude:
            # Drop already-shown scenes from the search response itself, so only the (at most
            # 3) remaining candidates cost a get_scene_context call. Not a rejected candidate.
            kept = [c for c in reply.candidates
                    if f'{c.chunk.video_id}:{c.selected_cue_id}' not in exclude]
            shown = len(kept) != len(reply.candidates)
            reply = reply.model_copy(update={'candidates':kept[:3]})
        results, _, timing, contexts = await ground_candidates(reply,self.metadata,counted)
        if exclude:
            # Safety net: grounding may resolve to a different cue key than selected_cue_id.
            shown = shown or any(evidence_key(r) in exclude for r in results)
            results = [r for r in results if evidence_key(r) not in exclude][:3]
        stats.latest_grounded = results
        stats.timing.update(timing)
        stats.note('context', grounded=[evidence_key(r) for r in results],
                   rejected=len(reply.candidates)-len(results))
        return {'grounded':results,'contexts':contexts,'timing':{**state.get('timing',{}),**timing},
                'round_all_rejected':bool(reply.candidates) and not results and not shown}

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
        # Judge only candidates not seen in an earlier round: identical candidates carry no
        # new information, so re-asking would only spend calls and can flip a verdict.
        # A verdict is reusable only for the same cue AND the same surrounding context the model
        # saw: overlapping chunks can select one cue with different neighbours.
        judged = dict(state.get('judged',{}))
        fingerprint = {evidence_key(r):self._judged_key(r,state['contexts'][evidence_key(r)])
                       for r in state['grounded']}
        new = [r for r in state['grounded'] if fingerprint[evidence_key(r)] not in judged]
        if new:
            evidence = []
            for r in new:
                context = state['contexts'][evidence_key(r)]
                evidence.append({'evidence_id':evidence_key(r),'quote':r.evidence_text,
                    'caption_type':r.evidence_type,
                    'context':[{'cue_id':c.cue_id,'text':c.original_text} for c in context.cues]})
            extra = ({'history':state['history'],'resolved_query':state['resolved_query']}
                     if state.get('resolved_query') else {})
            decision = await self._llm(stats,'verify',state['user_query'],evidence,**extra)
            expected = {evidence_key(r) for r in new}
            ids = [j.evidence_id for j in decision.judgments]
            if len(ids)!=len(set(ids)) or set(ids)!=expected:
                raise SearchFailure('model_invalid_evidence_ids')
            judged.update({fingerprint[j.evidence_id]:j.verdict for j in decision.judgments})
        verdicts = {evidence_key(r):judged[fingerprint[evidence_key(r)]] for r in state['grounded']}
        stats.note('verification', reused=len(state['grounded'])-len(new), verdicts=[
            {'evidence_id':evidence_key(r), 'start':r.start_seconds, 'quote':r.evidence_text,
             'verdict':verdicts[evidence_key(r)]} for r in state['grounded']])
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
        can_retry = not relevant and state['attempt'] < MAX_REPLAN_ROUNDS
        budget_ok = state['deadline']-time.monotonic() >= self.min_replan_budget
        # Nothing new to judge means another rewrite cannot change the outcome: stop.
        can_replan = can_retry and bool(new) and budget_ok
        warnings = list(state['warnings'])
        if can_retry and new and not budget_ok:
            warnings.append('replan_budget_exhausted')
        return {'verdicts':verdicts,'judged':judged,
                'relevant':relevant,'uncertain':uncertain_results,
                'can_replan':can_replan,'warnings':list(dict.fromkeys(warnings))}

    @staticmethod
    def _judged_key(result, context):
        cue_ids = ','.join(c.cue_id for c in context.cues)
        return f'{evidence_key(result)}|{hashlib.sha1(cue_ids.encode()).hexdigest()[:12]}'

    def _after_verification(self, state):
        return 'replan' if state.get('can_replan') else 'finalize'

    async def _replan(self, state, stats):
        # Rejected wording is shown so the rewrite changes key nouns instead of paraphrasing.
        feedback = [{'verdict':state['verdicts'].get(evidence_key(r),'unknown'),'quote':r.evidence_text[:120]}
                    for r in state['grounded']]
        query = await self._llm(stats,'rewrite',state.get('resolved_query') or state['user_query'],
                                state['queries'],feedback)
        query = SearchRequest(query=query).query
        stats.note('replan', previous=state['queries'], proposed=query)
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
        record['stage_tail_ms'] = stats.take_pending()
        # Numbers and model names only: token counts are the cost proxy for comparisons.
        usage = getattr(self.model,'usage',None) or {}
        start = getattr(stats,'usage_start',{})
        record['llm_backend'] = getattr(self.model,'name',None)
        record['llm_tokens_in'] = usage.get('tokens_in',0)-start.get('tokens_in',0)
        record['llm_tokens_out'] = usage.get('tokens_out',0)-start.get('tokens_out',0)
        self._write_trace(record, stats, state)
        try:
            self.log_path.parent.mkdir(parents=True,exist_ok=True)
            with self.log_path.open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(record,ensure_ascii=False)+'\n')
        except OSError:
            logger.warning('agent_log_failed request_id=%s',request_id)
        if self.telemetry is not None:
            self.telemetry.submit(record)
        return record

    def _tracing(self, request_id):
        telemetry = self.telemetry
        if telemetry is None or not telemetry.enabled or telemetry.client is None:
            return {'enabled': False}
        return {'enabled': True, 'client': telemetry.client,
                'project_name': os.getenv('LANGSMITH_PROJECT', 'wish-finder'),
                'metadata': {'request_id': request_id,
                             'llm_backend': getattr(self.model, 'name', None)},
                'tags': ['wish-finder']}

    def _write_trace(self, record, stats, state):
        """Private diagnostic dump; failures never affect the search response."""
        if self.trace_dir is None or stats.trace is None:
            return
        response = state.get('response') if state else None
        payload = {**record, 'user_query':stats.user_query, 'trace':stats.trace,
                   'warnings':response.warnings if response else [],
                   'results':[{'evidence_id':evidence_key(r), 'start':r.start_seconds,
                               'quote':r.evidence_text} for r in (response.results if response else [])]}
        try:
            self.trace_dir.mkdir(parents=True,exist_ok=True)
            name = f"{time.strftime('%Y%m%d-%H%M%S')}-{record['request_id']}.json"
            (self.trace_dir/name).write_text(json.dumps(payload,ensure_ascii=False,indent=1),encoding='utf-8')
        except OSError:
            logger.warning('agent_trace_failed request_id=%s',record['request_id'])

    async def run(self, query, *, request_id=None, history=None, exclude=None,
                  progress: Callable[[str,dict],Awaitable[None]] | None = None):
        query = SearchRequest(query=query).query
        request_id = request_id or str(uuid4())
        stats = RunStats(progress, trace=self.trace_dir is not None)
        stats.usage_start = dict(getattr(self.model,'usage',None) or {})
        stats.user_query = query
        started = time.monotonic()
        error = None
        state = None
        try:
            # Off unless the user opted in (WISH_LANGSMITH_ENABLED + key): ambient LangSmith
            # environment variables alone must not upload questions or subtitles.
            with tracing_context(**self._tracing(request_id)):
                async with asyncio.timeout(self.timeout):
                    state = await self.graph.ainvoke({'request_id':request_id,'user_query':query,
                        'history':history or [],'exclude':list(dict.fromkeys(exclude or [])),'attempt':0,'warnings':[],'timing':{},'deadline':started+self.timeout},
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
