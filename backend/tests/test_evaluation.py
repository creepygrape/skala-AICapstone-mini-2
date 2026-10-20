from types import SimpleNamespace
import asyncio
import json
import pytest

from eval.dataset import Question,load_questions,validate_source_labels
from eval.metrics import scene_metrics
from backend.app.services.video_catalog import Catalog,ROOT


def test_synthetic_labels_are_backed_by_source_cues():
    rows=load_questions(ROOT/'eval/dataset.example.jsonl')
    validate_source_labels(rows,Catalog(ROOT/'data/manifest.example.json'))
    bad=rows[0].model_copy(update={'evidence_cue_ids':['missing']})
    with pytest.raises(ValueError,match='Invalid source label'):
        validate_source_labels([bad],Catalog(ROOT/'data/manifest.example.json'))


def test_metrics_use_link_point_and_correct_video_not_interval_overlap():
    q=Question(id='one',query='test',split='dev',category='test',answerability='multiple_scenes',
               expected_video_id='SYNTHETIC01',accepted_intervals=[(100,110),(200,210)],evidence_cue_ids=['1'])
    def result(vid,start,end=1000):return SimpleNamespace(video_id=vid,start_seconds=start,end_seconds=end)
    assert scene_metrics(q,[result('SYNTHETIC01',10)])=={'scene_success_at_1':False,'hit_at_3':False}
    assert scene_metrics(q,[result('SYNTHETIC02',105),result('SYNTHETIC01',205)])=={'scene_success_at_1':False,'hit_at_3':True}
    assert scene_metrics(q,[result('SYNTHETIC01',90.9)])['scene_success_at_1']


def test_non_scene_and_pending_negative_do_not_enter_scene_denominator():
    q=Question(id='negative',query='test',split='gold_draft',category='negative',answerability='pending_not_found',
               expected_video_id=None,accepted_intervals=[],evidence_cue_ids=[])
    assert scene_metrics(q,[]) is None


def test_malformed_intervals_cannot_be_labels():
    with pytest.raises(ValueError):
        Question(id='bad',query='test',split='dev',category='test',answerability='scene_supported',
                 expected_video_id='SYNTHETIC01',accepted_intervals=[(3,1)],evidence_cue_ids=['1'])


def test_runner_refuses_draft_gold_before_loading_models_or_searching(tmp_path):
    from eval.run_eval import run
    rows=[json.loads(line) for line in (ROOT/'eval/dataset.example.jsonl').read_text().splitlines()]
    rows[0]['split']='gold_draft'
    path=tmp_path/'draft.jsonl';path.write_text(json.dumps(rows[0])+'\n')
    # No other args or model connection are needed: the guard runs first.
    with pytest.raises(ValueError,match='Draft gold is reserved'):
        asyncio.run(run(SimpleNamespace(dataset=path)))
