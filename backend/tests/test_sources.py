from pathlib import Path
import pytest

from backend.app.retrieval.srt_parser import parse_srt
from backend.app.retrieval.chunker import make_chunks
from backend.app.services.video_catalog import Catalog, ROOT
from backend.app.schemas import Cue


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


@pytest.mark.parametrize('previous,current', [('Go','Good morning'),('I',"It's fine"),('we',"we're fine")])
def test_prefix_dedup_does_not_cut_words(previous,current):
    cues=[Cue(video_id='SYNTHETIC01',cue_id=str(i),start_seconds=i,end_seconds=i+1,original_text=text)
          for i,text in enumerate([previous,current],1)]
    chunks=make_chunks(cues)
    assert current in chunks[0].text_for_retrieval
    assert cues[1].original_text==current


def test_repeated_complete_prefix_is_removed_only_from_search_text():
    cues=[Cue(video_id='SYNTHETIC01',cue_id=str(i),start_seconds=i,end_seconds=i+1,original_text=text)
          for i,text in enumerate(['(Applause everyone)','(Applause everyone) Beef festival?'],1)]
    chunk=make_chunks(cues)[0]
    assert chunk.text_for_retrieval=='(Applause everyone)\nBeef festival?'
    assert cues[1].original_text=='(Applause everyone) Beef festival?'
    assert chunk.cue_ids==('1','2')


def test_srt_multiple_blank_lines_and_structural_spaces_preserve_text(tmp_path):
    path=tmp_path/'spaced.srt'
    path.write_text(' 1 \n 00:00:01,000 --> 00:00:02,000 \n  first caption  \n\n \n\n 2 \n00:00:02,000 --> 00:00:03,000 \n second caption ')
    cues=parse_srt(path,'SYNTHETIC01')
    assert [c.cue_id for c in cues]==['1','2']
    assert [c.original_text for c in cues]==['  first caption  ',' second caption ']


def test_manifest_resolution_is_independent_of_working_directory(monkeypatch,tmp_path):
    from backend.app.services.video_catalog import load_videos,resolve_manifest
    monkeypatch.setenv('WISH_MANIFEST','data/manifest.example.json')
    expected=resolve_manifest()
    monkeypatch.chdir(tmp_path)
    assert resolve_manifest()==expected==ROOT/'data/manifest.example.json'
    assert load_videos()[0].video_id=='SYNTHETIC01'
    assert len(Catalog().cues['SYNTHETIC01'])==4
