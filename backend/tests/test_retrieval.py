from backend.app.services.video_catalog import Catalog,ROOT
from backend.app.retrieval.hybrid import Retriever
import pytest


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
