from pathlib import Path
import pytest

from backend.app.retrieval.srt_parser import parse_srt
from backend.app.retrieval.chunker import make_chunks
from backend.app.services.video_catalog import Catalog, ROOT


def test_fixture_preserves_mixed_caption_and_unknown_speakers():
    cues = parse_srt(ROOT / "data/fixtures/synthetic.srt", "SYNTHETIC01")
    assert cues[1].original_text == "(RIKU chose RIKU) Got myself"
    assert cues[1].caption_type == "mixed"
    assert cues[1].mentioned_members == ("RIKU",)
    assert all(c.speaker is None for c in cues)
    assert cues[0].mentioned_members == ()  # Ryokan must not match RYO.
    assert cues[2].mentioned_members == ("SAKUYA",)


def test_long_cue_is_not_repeated_and_video_boundaries_are_preserved():
    cues = parse_srt(ROOT / "data/fixtures/synthetic.srt", "SYNTHETIC01")
    other = [c.model_copy(update={"video_id":"SYNTHETIC02"}) for c in cues]
    chunks = make_chunks(cues + other)
    for video in ["SYNTHETIC01","SYNTHETIC02"]:
        long_chunks = [c for c in chunks if c.video_id==video and "4" in c.cue_ids]
        assert len(long_chunks)==1 and long_chunks[0].long_cue
        assert long_chunks[0].end_seconds == 105.091
        assert set(i for c in chunks if c.video_id==video for i in c.cue_ids)=={"1","2","3","4"}


@pytest.mark.parametrize("body", [
    "1\n00:00:02,000 --> 00:00:01,000\ninvalid\n",
    "1\n00:99:01,000 --> 00:99:02,000\ninvalid\n",
    "1\n00:00:01,000 --> 00:00:02,000\na\n\n1\n00:00:02,000 --> 00:00:03,000\nb\n",
])
def test_invalid_cues_are_rejected(tmp_path, body):
    path=tmp_path/'bad.srt';path.write_text(body)
    with pytest.raises(ValueError): parse_srt(path,"SYNTHETIC01")


def test_bom_crlf_overlap_and_repetition_are_preserved(tmp_path):
    path=tmp_path/'bom.srt'
    path.write_bytes(b'\xef\xbb\xbf1\r\n00:00:01,000 --> 00:00:03,000\r\nEcho\r\n\r\n2\r\n00:00:02,000 --> 00:00:04,000\r\nEcho\r\n')
    cues=parse_srt(path,"SYNTHETIC01")
    assert len(cues)==2 and cues[0].original_text==cues[1].original_text=='Echo'


def test_local_corpus_if_present():
    if not (ROOT/'data/manifest.local.json').exists():
        pytest.skip('Private corpus not available')
    catalog=Catalog()
    assert {v:len(c) for v,c in catalog.cues.items()} == {'1HJgbE66GI4':1534,'vWjPXwKV_Y8':1558,'zOgJILPNzbE':658}
    cue=next(c for c in catalog.cues['1HJgbE66GI4'] if c.cue_id=='1220')
    assert cue.end_seconds-cue.start_seconds==pytest.approx(75.091)
