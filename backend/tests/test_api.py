"""JSON API integration with real MCP and synthetic source; no model download."""

from fastapi.testclient import TestClient
import pytest

from backend.app.main import app
from backend.app.services.video_catalog import ROOT
from backend.app.services.evidence import verify_candidate
from backend.app.schemas import Candidate, Chunk, ContextReply, MetadataReply


def test_json_search_through_real_mcp(monkeypatch):
    monkeypatch.setenv('WISH_MANIFEST',str(ROOT/'data/manifest.example.json'))
    monkeypatch.setenv('WISH_KEYWORD_ONLY','1')
    with TestClient(app) as client:
        assert client.get('/ready').status_code==200
        assert len(client.get('/api/videos').json()['videos'])==1
        assert client.post('/api/search',json={'query':'  '}).status_code==422
        result=client.post('/api/search',json={'query':'RIKU chose RIKU'})
        assert result.status_code==200,result.text
        body=result.json()
        assert body['status']=='partial' and 'semantic_verification_skipped' in body['warnings']
        item=body['results'][0]
        assert item['evidence_text']=='(RIKU chose RIKU) Got myself'
        assert item['speaker'] is None and item['speaker_status']=='unknown'
        assert item['url']=='https://www.youtube.com/watch?v=SYNTHETIC01&t=3s'
        assert client.post('/api/search',json={'query':'spaceship zebra'}).json()['status']=='not_found'
        app.state.busy=True
        assert client.post('/api/search',json={'query':'RIKU'}).status_code==503
        app.state.busy=False


def test_evidence_rejects_missing_or_cross_video_cues():
    candidate=Candidate(chunk=Chunk(chunk_id='one',video_id='SYNTHETIC01',cue_ids=('1',),
        start_seconds=1,end_seconds=3,text_for_retrieval='test'),score=1,selected_cue_id='2')
    context=ContextReply(video_id='SYNTHETIC01',cues=[])
    metadata=MetadataReply(video_id='SYNTHETIC01',title='synthetic',url='unused',title_verified=False,timing_verified=False)
    with pytest.raises(ValueError,match='outside candidate'):
        verify_candidate(candidate,context,metadata)
    context.video_id='SYNTHETIC02'
    with pytest.raises(ValueError,match='video mismatch'):
        verify_candidate(candidate,context,metadata)


@pytest.mark.parametrize('all_rejected',[False,True])
def test_candidate_rejection_is_not_a_tool_failure(monkeypatch,all_rejected):
    import backend.app.main as module
    original=module.call

    async def inject(session,name,arguments,schema):
        reply=await original(session,name,arguments,schema)
        if name=='search_transcripts':
            bad=reply.candidates[0].model_copy(deep=True)
            bad.selected_cue_id='outside-candidate'
            reply.candidates=[bad] if all_rejected else [bad,reply.candidates[0]]
        return reply

    monkeypatch.setenv('WISH_MANIFEST','data/manifest.example.json')
    monkeypatch.setenv('WISH_KEYWORD_ONLY','1')
    monkeypatch.setattr(module,'call',inject)
    with TestClient(app) as client:
        result=client.post('/api/search',json={'query':'RIKU'})
        assert result.status_code==200,result.text
        body=result.json()
        assert 'evidence_rejected' in body['warnings']
        assert body['status']==('unsupported' if all_rejected else 'partial')
        assert len(body['results'])==(0 if all_rejected else 1)


def test_metadata_is_cached_and_tool_errors_stay_503(monkeypatch):
    import backend.app.main as module
    original=module.call
    metadata_calls=[]
    fail_search=False

    async def track(session,name,arguments,schema):
        if name=='get_video_metadata': metadata_calls.append(arguments['video_id'])
        if name=='search_transcripts' and fail_search: raise RuntimeError('injected MCP failure')
        return await original(session,name,arguments,schema)

    monkeypatch.setenv('WISH_MANIFEST','data/manifest.example.json')
    monkeypatch.setenv('WISH_KEYWORD_ONLY','1')
    monkeypatch.setattr(module,'call',track)
    with TestClient(app) as client:
        assert metadata_calls==['SYNTHETIC01']
        assert client.get('/api/videos').status_code==200
        assert client.get('/api/videos').status_code==200
        assert client.post('/api/search',json={'query':'RIKU'}).status_code==200
        assert metadata_calls==['SYNTHETIC01']
        fail_search=True
        response=client.post('/api/search',json={'query':'RIKU'})
        assert response.status_code==503
        assert response.json()['detail']['request_id']
        assert not app.state.busy


def test_url_builder_validates_id_and_time():
    from backend.app.services.urls import video_url
    assert video_url('1HJgbE66GI4')=='https://www.youtube.com/watch?v=1HJgbE66GI4'
    assert video_url('1HJgbE66GI4',189.606).endswith('&t=189s')
    for video_id,start in [('bad-id',1),('1HJgbE66GI4',-1),('1HJgbE66GI4',float('nan'))]:
        with pytest.raises(ValueError): video_url(video_id,start)


def test_user_sampled_timing_flag_is_reflected_in_metadata_and_warnings(monkeypatch,tmp_path):
    import json
    rows=json.loads((ROOT/'data/manifest.example.json').read_text())
    rows[0]['timing_verified']=True
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(rows))
    monkeypatch.setenv('WISH_MANIFEST',str(manifest))
    monkeypatch.setenv('WISH_KEYWORD_ONLY','1')
    with TestClient(app) as client:
        assert client.get('/api/videos').json()['videos'][0]['timing_verified']
        body=client.post('/api/search',json={'query':'RIKU'}).json()
        assert body['results']
        assert 'video_timing_unverified' not in body['warnings']
        assert 'video_timing_sampled' in body['warnings']
        assert 'semantic_verification_skipped' in body['warnings']
