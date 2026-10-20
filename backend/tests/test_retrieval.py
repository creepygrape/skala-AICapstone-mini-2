from backend.app.services.video_catalog import Catalog,ROOT
from backend.app.retrieval.hybrid import Retriever
import pytest
import numpy as np


def test_keyword_source_references_and_mode_failures():
    catalog=Catalog(ROOT/'data/manifest.example.json')
    retriever=Retriever(catalog)
    reply=retriever.search('RIKU chose RIKU','keyword')
    assert reply.candidates
    cue=retriever.select_cue('RIKU chose RIKU',reply.candidates[0])
    assert cue.cue_id=='2' and cue.speaker is None
    assert retriever.search('zebra spaceship','keyword').candidates==[]
    with pytest.raises(RuntimeError): retriever.search('test','hybrid')
    with pytest.raises(ValueError): retriever.search('test','keyword',video_ids=['unknown'])


def test_query_vector_is_reused_for_all_candidates_and_keyword_never_embeds():
    class Encoder:
        identity='synthetic-counting-encoder'
        def __init__(self): self.calls=[]
        def encode(self,texts):
            self.calls.append(list(texts))
            return np.array([[1.,1.] for _ in texts]) / np.sqrt(2)
    catalog=Catalog(ROOT/'data/manifest.example.json')
    encoder=Encoder()
    retriever=Retriever(catalog,encoder)
    encoder.calls.clear()
    result=retriever.search('unique query','hybrid')
    assert result.candidates
    assert encoder.calls.count(['unique query'])==1
    assert all(c.selected_cue_id in c.chunk.cue_ids for c in result.candidates)
    encoder.calls.clear()
    retriever.search('RIKU','keyword')
    assert encoder.calls==[]
