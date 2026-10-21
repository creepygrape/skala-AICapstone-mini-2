"""Chunk window/stride are configurable for the chunk-length comparison (defaults unchanged)."""

import pytest

from backend.app.retrieval.chunker import chunk_settings, make_chunks
from backend.app.retrieval.hybrid import Retriever
from backend.app.services.video_catalog import Catalog, ROOT


def test_defaults_are_the_documented_20_10():
    assert chunk_settings({}) == (20, 10)
    assert chunk_settings({"WISH_CHUNK_WINDOW": "", "WISH_CHUNK_STRIDE": ""}) == (20, 10)


def test_valid_overrides_are_read():
    assert chunk_settings({"WISH_CHUNK_WINDOW": "30", "WISH_CHUNK_STRIDE": "15"}) == (30, 15)
    assert chunk_settings({"WISH_CHUNK_WINDOW": "10"}) == (10, 10)           # stride stays 10, window 10: no overlap


@pytest.mark.parametrize("env", [
    {"WISH_CHUNK_WINDOW": "abc"},
    {"WISH_CHUNK_STRIDE": "0"},
    {"WISH_CHUNK_STRIDE": "-5"},
    {"WISH_CHUNK_WINDOW": "10", "WISH_CHUNK_STRIDE": "20"},                   # stride larger than window leaves gaps
    {"WISH_CHUNK_WINDOW": "500", "WISH_CHUNK_STRIDE": "10"},                  # absurd window
])
def test_invalid_settings_fail_with_a_clear_message(env):
    with pytest.raises(ValueError, match="WISH_CHUNK"):
        chunk_settings(env)


@pytest.mark.parametrize("window,stride", [(20, 10), (10, 5), (30, 15), (20, 20), (40, 10)])
def test_every_setting_keeps_cue_references_and_covers_all_cues(window, stride):
    catalog = Catalog(ROOT / "data/manifest.example.json")
    cues = [c for group in catalog.cues.values() for c in group]
    chunks = make_chunks(cues, window, stride)
    known = {(c.video_id, c.cue_id) for c in cues}
    seen = set()
    for chunk in chunks:
        assert chunk.start_seconds <= chunk.end_seconds
        assert {(chunk.video_id, i) for i in chunk.cue_ids} <= known         # only real cues of that video
        seen |= {(chunk.video_id, i) for i in chunk.cue_ids}
    assert seen == known                                                      # no cue is lost whatever the setting


def test_retriever_uses_the_configured_chunking_and_still_searches():
    catalog = Catalog(ROOT / "data/manifest.example.json")
    default = Retriever(catalog)
    wide = Retriever(catalog, chunk_window=40, chunk_stride=20)
    assert (default.chunk_window, default.chunk_stride) == (20, 10)
    assert (wide.chunk_window, wide.chunk_stride) == (40, 20)
    for retriever in (default, wide):
        reply = retriever.search("ryokan", "keyword", 3)
        assert reply.candidates and all(c.selected_cue_id in c.chunk.cue_ids for c in reply.candidates)
