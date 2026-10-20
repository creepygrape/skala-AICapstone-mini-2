import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace

import pytest

from backend.app.schemas import SearchResponse
from backend.app.services.video_catalog import ROOT, Catalog
from backend.tests.test_search_service import FakeSession
from eval.dataset import load_questions, validate_source_labels
from eval.metrics import answerability_metrics, summarize
from eval.paths import project_path, private_output


def test_all_relative_paths_are_root_based(monkeypatch,tmp_path):
    import eval.paths as paths
    monkeypatch.setattr(paths,'ROOT',tmp_path)
    elsewhere=tmp_path/'backend';elsewhere.mkdir();monkeypatch.chdir(elsewhere)
    assert project_path('eval/private/dev.jsonl')==tmp_path/'eval/private/dev.jsonl'
    assert private_output('eval/private/result.json')==tmp_path/'eval/private/result.json'


@pytest.mark.parametrize('name',['../outside.json','eval/public.json','/private/tmp/exposed.json','eval/private/../../../outside.json'])
def test_output_path_cannot_escape_private(monkeypatch,tmp_path,name):
    import eval.paths as paths
    monkeypatch.setattr(paths,'ROOT',tmp_path)
    with pytest.raises(ValueError): private_output(name)


def test_output_symlink_escape_and_relocated_private_root_are_rejected(monkeypatch,tmp_path):
    import eval.paths as paths
    monkeypatch.setattr(paths,'ROOT',tmp_path)
    root=tmp_path/'eval/private';root.mkdir(parents=True)
    outside=tmp_path/'public';outside.mkdir()
    (root/'link').symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError): private_output('eval/private/link/leak.json')
    other=tmp_path/'other';other.mkdir();(other/'eval').symlink_to(tmp_path/'eval',target_is_directory=True)
    monkeypatch.setattr(paths,'ROOT',other)
    with pytest.raises(ValueError): private_output('eval/private/result.json')


def test_every_accepted_interval_requires_source_evidence():
    catalog=Catalog(ROOT/'data/manifest.example.json')
    q=load_questions(ROOT/'eval/dataset.example.jsonl')[0]
    bad=q.model_copy(update={'accepted_intervals':[(3,4),(500,600)]})
    with pytest.raises(ValueError,match='Unbacked accepted interval'):
        validate_source_labels([bad],catalog)
    good=q.model_copy(update={'accepted_intervals':[(3,4),(30,105.091)],'evidence_cue_ids':['2','4']})
    validate_source_labels([good],catalog)


def test_abstention_and_speaker_metrics_are_separate_from_visual_capability():
    q=load_questions(ROOT/'eval/dataset.example.jsonl')[0]
    response=SearchResponse(request_id='test',status='not_found',search_attempts=1,warnings=['speaker_unknown'])
    negative=q.model_copy(update={'answerability':'not_found'})
    assert answerability_metrics(negative,response)['not_found_correct'] is True
    error=response.model_copy(update={'status':'error'})
    assert answerability_metrics(negative,error)['not_found_correct'] is False
    speaker=q.model_copy(update={'answerability':'speaker_unknown'})
    assert answerability_metrics(speaker,response)['speaker_unknown_correct'] is True
    assert answerability_metrics(speaker,error)['speaker_unknown_correct'] is False
    visual=q.model_copy(update={'answerability':'visual_unsupported'})
    assert answerability_metrics(visual,response)['unsupported_correct'] is None
    assert answerability_metrics(visual,response)['unsupported_reason']=='baseline_has_no_intent_router'
    tasks=[{'condition':'raw_ko','system':'A','question':visual}]
    summary=summarize([],tasks)[0]
    assert summary['unsupported_accuracy']['accuracy'] is None
    assert summary['unsupported_accuracy']['planned_denominator']==1
    assert summary['scene_success_at_1']['accuracy'] is None


@pytest.mark.parametrize('behavior,complete,executed',[('tool_error',True,4),('fatal',False,2)])
def test_runner_preserves_errors_and_unexecuted_tasks(monkeypatch,tmp_path,behavior,complete,executed):
    import eval.paths as paths
    import eval.run_eval as runner
    monkeypatch.setattr(paths,'ROOT',tmp_path)
    rows=[json.loads((ROOT/'eval/dataset.example.jsonl').read_text())]
    rows.append(dict(rows[0],id='synthetic-second'))
    dataset=tmp_path/'dev.jsonl';dataset.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    session=FakeSession(behavior,fail_search_number=2)
    @asynccontextmanager
    async def fake_connect(**kwargs): yield session
    monkeypatch.setattr(runner,'connect',fake_connect)
    target=tmp_path/'eval/private/results.json'
    result=asyncio.run(runner.run(SimpleNamespace(dataset=dataset,rewrites=None,
        manifest=ROOT/'data/manifest.example.json',output=target)))
    stored=json.loads(target.read_text())
    assert stored['complete']==complete
    assert len(stored['records'])==executed
    assert stored['records'][1]['status']=='error'
    assert stored['records'][1]['tool_calls']==1
    assert stored['summary'][0]['scene_questions']==2  # Error is not excluded.
    assert stored['summary'][0]['success_at_1_count']==1
    assert len(stored['not_run'])==4-executed
    assert result==stored
    with pytest.raises(ValueError,match='Output already exists'):
        asyncio.run(runner.run(SimpleNamespace(dataset=dataset,rewrites=None,
            manifest=ROOT/'data/manifest.example.json',output=target)))
