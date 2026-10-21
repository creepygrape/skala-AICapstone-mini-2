"""C evaluation path: real FinderAgent graph with scripted model; no Ollama."""

import asyncio
import json

import pytest

from backend.app.services.video_catalog import ROOT
from eval.agent_runner import RouteProbe, evaluate_agent_question
from eval.dataset import load_questions
from eval.metrics import agent_metrics, summarize
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
