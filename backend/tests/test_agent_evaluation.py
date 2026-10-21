"""C evaluation path: real FinderAgent graph with scripted model; no Ollama."""

import asyncio
import json

import pytest

from backend.app.services.search import SearchFailure
from backend.app.services.video_catalog import ROOT
from eval.agent_runner import RouteProbe, evaluate_agent_question
from eval.dataset import load_questions
from eval.metrics import agent_metrics, scene_metrics, summarize
from eval.run_eval import verify_gold_approval
from backend.tests.test_agent import ScriptedModel, make_agent


def question(answerability='scene_supported'):
    q = load_questions(ROOT/'eval/dataset.example.jsonl')[0]
    if answerability == 'visual_unsupported':
        return q.model_copy(update={'answerability':answerability,'expected_video_id':None,
                                    'accepted_intervals':[],'evidence_cue_ids':[]})
    return q.model_copy(update={'answerability':answerability})


def run_c(tmp_path, q, intent='scene_search', override=None, verdicts=('relevant',)):
    model = ScriptedModel(verdicts, intent=intent)
    agent, session = make_agent(tmp_path, RouteProbe(model))
    probe = agent.model
    record = asyncio.run(evaluate_agent_question(agent, probe, q, condition='c', system='C', override=override))
    return record, session


def test_speaker_query_needs_intent_scene_and_notice(tmp_path):
    q = question('speaker_unknown')
    record, _ = run_c(tmp_path, q, intent='speaker_query')
    m = record['agent_metrics']
    assert (m['speaker_intent_ok'], m['speaker_scene_ok'], m['speaker_notice_ok']) == (True, True, True)
    assert m['speaker_unknown_correct'] is True
    assert record['llm_calls'] == 2 and record['tool_calls'] >= 2
    # Same scene, but the Router did not classify it as a speaker query: not correct.
    wrong, _ = run_c(tmp_path, q, intent='scene_search')
    assert wrong['agent_metrics']['speaker_notice_ok'] is False
    assert wrong['agent_metrics']['speaker_unknown_correct'] is False


def test_visual_request_requires_unsupported_intent_and_no_results(tmp_path):
    q = question('visual_unsupported')
    ok, _ = run_c(tmp_path, q, intent='unsupported')
    assert ok['agent_metrics']['unsupported_correct'] is True and ok['results'] == []
    bad, _ = run_c(tmp_path, q, intent='scene_search')
    assert bad['agent_metrics']['unsupported_correct'] is False


def test_override_replaces_only_the_query_and_router_query_is_captured(tmp_path):
    record, session = run_c(tmp_path, question(), override='fixed starting query')
    assert record['initial_query_source'] == 'fixed_override'
    assert record['router_first_query'] == 'RIKU chose RIKU'
    assert session.queries[0] == 'fixed starting query'


def test_scene_misrouted_and_replan_cap_are_recorded(tmp_path):
    record, session = run_c(tmp_path, question(), intent='unsupported')
    assert record['agent_metrics']['scene_misrouted'] is True and record['results'] == []
    capped, session = run_c(tmp_path, question(), verdicts=('irrelevant',))
    assert capped['search_rounds'] == 3 == len(session.queries) and capped['status'] == 'not_found'


def test_agent_failure_stays_in_measured_denominator(tmp_path):
    model = ScriptedModel()
    agent, _ = make_agent(tmp_path, RouteProbe(model), behavior='tool_error')
    record = asyncio.run(evaluate_agent_question(agent, agent.model, question(),
                                                 condition='c', system='C'))
    assert record['status'] == 'error' and record['error']['code']
    summary = summarize([record], [{'condition':'c','system':'C','question':question()}])[0]
    assert summary['error_questions'] == 1 and summary['scene_questions'] == 1
    assert summary['success_at_1_count'] == 0


def test_summary_counts_llm_and_tool_calls_for_c(tmp_path):
    q = question('speaker_unknown')
    record, _ = run_c(tmp_path, q, intent='speaker_query')
    s = summarize([record], [{'condition':'c','system':'C','question':q}])[0]
    assert s['speaker_unknown_accuracy']['accuracy'] == 1.0
    assert s['total_llm_calls'] == 2 and s['mean_tool_calls'] == record['tool_calls']
    assert s['unsupported_speaker_assertions'] == 0


def test_gold_approval_hash_is_enforced(tmp_path, monkeypatch):
    import eval.run_eval as runner
    private = tmp_path/'eval/private'; private.mkdir(parents=True)
    row = json.loads((ROOT/'eval/dataset.example.jsonl').read_text().splitlines()[0])
    row.update(split='gold', label_status='accepted')
    gold = private/'gold.jsonl'; gold.write_text(json.dumps(row)+'\n')
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    rows = load_questions(gold)
    with pytest.raises(ValueError, match='no recorded human approval'):
        verify_gold_approval(gold, rows)
    import hashlib
    approval = {'approved_by':'user','approved_at':'x','approved_count':1,'approved_ids':[row['id']],
                'gold_sha256':hashlib.sha256(gold.read_bytes()).hexdigest()}
    (private/'gold-approval.json').write_text(json.dumps(approval))
    assert verify_gold_approval(gold, rows)['approved_count'] == 1
    gold.write_text(json.dumps(row).replace('RIKU', 'X')+'\n')
    with pytest.raises(ValueError, match='changed after human approval'):
        verify_gold_approval(gold, load_questions(gold))


class FailingModel(ScriptedModel):
    """ScriptedModel that fails at a chosen stage."""
    def __init__(self, fail, **kwargs):
        super().__init__(**kwargs)
        self.fail = fail

    async def route(self, query):
        if self.fail == 'route':
            raise SearchFailure('model_unavailable')
        return await super().route(query)

    async def verify(self, query, evidence):
        if self.fail == 'verify':
            raise SearchFailure('model_timeout')
        return await super().verify(query, evidence)

    async def rewrite(self, query, previous, feedback):
        if self.fail == 'rewrite':
            raise SearchFailure('model_timeout')
        return await super().rewrite(query, previous, feedback)


def run_with(tmp_path, model, q):
    agent, _ = make_agent(tmp_path, RouteProbe(model))
    return asyncio.run(evaluate_agent_question(agent, agent.model, q, condition='c', system='C'))


def test_ambiguous_is_not_scene_or_speaker_success(tmp_path):
    q = question('speaker_unknown')
    record = run_with(tmp_path, ScriptedModel(('uncertain',), intent='speaker_query'), q)
    assert record['status'] == 'ambiguous'
    assert record['retrieval_metrics']['scene_success_at_1'] is True  # raw candidate hit kept apart
    assert record['metrics'] == {'scene_success_at_1':False, 'hit_at_3':False}
    assert record['agent_metrics']['speaker_unknown_correct'] is False
    s = summarize([record], [{'condition':'c','system':'C','question':q}])[0]
    assert s['success_at_1_count'] == 0 and s['raw_retrieval_success_at_1_count'] == 1


def test_partial_after_verifier_error_is_not_success_and_keeps_cause(tmp_path):
    q = question()
    record = run_with(tmp_path, FailingModel('verify'), q)
    assert record['status'] == 'partial' and record['error'] is None
    assert record['fallback'] is True and record['telemetry_error'] == 'model_timeout'
    assert record['metrics']['scene_success_at_1'] is False
    assert record['retrieval_metrics']['scene_success_at_1'] is True
    assert record['llm_calls'] == 2 and not record['llm_calls_mismatch']
    s = summarize([record], [{'condition':'c','system':'C','question':q}])[0]
    assert s['fallback_questions'] == 1 and s['success_at_1_count'] == 0


def test_router_failure_keeps_llm_call_count(tmp_path):
    record = run_with(tmp_path, FailingModel('route'), question())
    assert record['status'] == 'error' and record['error']['code'] == 'model_unavailable'
    assert record['llm_calls'] == 1 and record['fallback'] is False


def test_rewrite_error_after_uncertain_is_ambiguous_fallback(tmp_path):
    q = question()
    record = run_with(tmp_path, FailingModel('rewrite', verdicts=('irrelevant',)), q)
    # Nothing uncertain was kept, so a failed rewrite is a request error with its cost preserved.
    assert record['status'] == 'error' and record['llm_calls'] == 3
    class UncertainThenFail(FailingModel):
        async def verify(self, query, evidence):
            return await ScriptedModel.verify(self, query, evidence)
    model = UncertainThenFail('rewrite', verdicts=('uncertain',))
    record = run_with(tmp_path, model, q)
    assert record['status'] == 'ambiguous' and record['telemetry_error'] == 'model_timeout'
    assert record['metrics']['scene_success_at_1'] is False and record['llm_calls'] == 3


def test_ab_partial_still_counts_as_search_candidate():
    from types import SimpleNamespace
    q = question()
    hit = SimpleNamespace(video_id=q.expected_video_id, start_seconds=q.accepted_intervals[0][0])
    assert scene_metrics(q, [hit])['scene_success_at_1'] is True


def test_aggregate_counts_only_found_for_c_and_flags_confident_wrong():
    from eval.aggregate import aggregate
    hit = {'scene_success_at_1':True, 'hit_at_3':True}
    miss = {'scene_success_at_1':False, 'hit_at_3':False}
    def rec(system, status, m, **kw):
        return {'condition':'c', 'system':system, 'status':status, 'metrics':m, **kw}
    rows = aggregate([rec('C', 'found', hit), rec('C', 'ambiguous', hit), rec('C', 'found', miss),
                      rec('C', 'unsupported', None), rec('B', 'partial', hit)])
    c, b = rows[('c', 'C')], rows[('c', 'B')]
    assert (c['success_at_1'], c['raw_success_at_1'], c['confident_wrong'], c['scene_questions']) == (1, 2, 1, 3)
    assert b['success_at_1'] == 1  # A/B partial results remain search hits


def test_llm_budget_guard_stops_before_a_question_could_exceed_the_cap():
    from eval.run_eval import llm_budget_exhausted
    assert llm_budget_exhausted(1000, None) is False
    assert llm_budget_exhausted(0, 6) is False        # a worst-case question (6 calls) still fits
    assert llm_budget_exhausted(1, 6) is True
    assert llm_budget_exhausted(144, 150) is False and llm_budget_exhausted(145, 150) is True


def test_probe_reports_tokens_spent_per_question_and_summary_totals_them(tmp_path):
    class Counting(ScriptedModel):
        usage = {'calls': 0, 'tokens_in': 0, 'tokens_out': 0}
        async def route(self, query):
            self.usage.update(calls=self.usage['calls']+1, tokens_in=self.usage['tokens_in']+10,
                              tokens_out=self.usage['tokens_out']+2)
            return await super().route(query)
        async def verify(self, query, evidence):
            self.usage.update(calls=self.usage['calls']+1, tokens_in=self.usage['tokens_in']+30,
                              tokens_out=self.usage['tokens_out']+5)
            return await super().verify(query, evidence)
    model = Counting(('relevant',))
    agent, _ = make_agent(tmp_path, RouteProbe(model))
    probe = agent.model
    q = question()
    first = asyncio.run(evaluate_agent_question(agent, probe, q, condition='c', system='C'))
    second = asyncio.run(evaluate_agent_question(agent, probe, q, condition='c', system='C'))
    for record in (first, second):  # per-question delta, not cumulative
        assert (record['llm_tokens_in'], record['llm_tokens_out']) == (40, 7)
    from eval.aggregate import aggregate
    row = aggregate([first, second])[('c', 'C')]
    assert (row['llm_tokens_in'], row['llm_tokens_out']) == (80, 14)


def test_langsmith_for_eval_is_explicit_and_refuses_to_run_untraced(monkeypatch):
    import backend.app.agent.telemetry as telemetry
    from eval.run_eval import start_langsmith
    class Client:
        def __init__(self, **kwargs): pass
        def close(self): pass
    monkeypatch.setattr(telemetry, 'Client', Client)
    monkeypatch.delenv('LANGSMITH_PROJECT', raising=False)
    monkeypatch.delenv('WISH_LANGSMITH_ENABLED', raising=False)
    monkeypatch.delenv('LANGSMITH_API_KEY', raising=False)
    assert asyncio.run(start_langsmith(False)) is None          # off unless asked
    with pytest.raises(ValueError):                                # asked but not configured
        asyncio.run(start_langsmith(True))
    monkeypatch.setenv('WISH_LANGSMITH_ENABLED', '1')
    monkeypatch.setenv('LANGSMITH_API_KEY', 'synthetic-test-key')
    async def run():
        publisher = await start_langsmith(True)
        assert publisher.enabled and publisher.client is not None
        await publisher.close()
    asyncio.run(run())
    import os
    assert os.environ.pop('LANGSMITH_PROJECT') == 'wish-finder-eval'  # separate from web traffic
