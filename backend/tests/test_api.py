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
