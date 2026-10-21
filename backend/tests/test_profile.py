"""Collection profile: generic by default, collection knowledge only from data/."""

import json

import pytest

from backend.app.agent.model import (INSTRUCTIONS, ROUTE_TASK, REWRITE_TASK, VERIFY_TASK, OllamaModel,
                                     build_model)
from backend.app.profile import Profile, load_profile
from backend.app.services.video_catalog import ROOT

EXAMPLE = ROOT / 'data/profile.example.json'


def test_default_profile_is_generic_and_mentions_no_collection():
    profile = Profile()
    text = ' '.join([INSTRUCTIONS, profile.render(), ROUTE_TASK, VERIFY_TASK, REWRITE_TASK])
    assert 'WISH' not in text and 'NCT' not in text
    assert profile.subtitle_language == 'English' and profile.mentions('RIKU chose RIKU') == ()


def test_example_profile_renders_languages_translation_note_and_names():
    profile = load_profile(EXAMPLE)
    rendered = profile.render()
    assert 'Subtitle language: English' in rendered
    assert 'translated from Korean and Japanese' in rendered
    assert 'RIKU = 리쿠, リク' in rendered and 'write the spelling before "="' in rendered


def test_mentions_use_whole_words_and_never_become_speakers():
    profile = load_profile(EXAMPLE)
    assert profile.mentions('(RIKU chose RIKU) Got myself') == ('RIKU',)
    assert profile.mentions('What is a ryokan?') == ()          # ryokan must not match RYO
    assert profile.mentions('SAKUYA, look over there.') == ('SAKUYA',)
    assert profile.mentions('리쿠가 뽑았다') == ('RIKU',)        # alias in another script


def test_missing_profile_file_means_generic_but_an_invalid_one_fails_fast(tmp_path, monkeypatch):
    assert load_profile(ROOT / 'data/does-not-exist.json') == Profile()
    broken = ROOT / 'data/profile.broken-test.json'
    broken.write_text(json.dumps({'unknown_field': 1}), encoding='utf-8')
    try:
        with pytest.raises(Exception):
            load_profile(broken)
    finally:
        broken.unlink()


def test_profile_must_live_under_data():
    with pytest.raises(ValueError):
        load_profile('/tmp/profile.json')
    with pytest.raises(ValueError):
        load_profile(ROOT / 'README.md')


def test_prompts_carry_the_profile_language_names_and_rules_for_both_backends():
    profile = load_profile(EXAMPLE)
    for model in (OllamaModel(profile=profile), build_model({'WISH_LLM_BACKEND': 'openai'}, profile=profile)):
        system = model.messages(ROUTE_TASK.format(lang=profile.subtitle_language), {'question': 'q'})[0]['content']
        assert 'RIKU = 리쿠' in system and 'concise English retrieval query' in system
        assert 'translations or paraphrases' in system
    verify = OllamaModel(profile=profile).messages(VERIFY_TASK, {})[0]['content']
    assert 'must NOT lower the verdict' in verify and 'accept the same meaning' in verify
    assert 'change the' not in verify
    rewrite = REWRITE_TASK.format(lang='English')
    assert 'key nouns' in rewrite and 'Never repeat a previous query' in rewrite


def test_another_collection_changes_prompts_without_touching_code():
    other = Profile(name='cooking videos', subtitle_language='Japanese')
    system = OllamaModel(profile=other).messages(ROUTE_TASK.format(lang=other.subtitle_language), {})[0]['content']
    assert 'cooking videos' in system and 'concise Japanese retrieval query' in system and 'WISH' not in system


@pytest.mark.parametrize('entity', [
    {'canonical': '   '}, {'canonical': ''},
    {'canonical': 'RIKU', 'aliases': ['']}, {'canonical': 'RIKU', 'aliases': ['  ']},
    {'canonical': 'RIKU', 'aliases': ['x' * 41]},
])
def test_blank_names_and_aliases_are_rejected_before_they_can_match_every_line(entity):
    with pytest.raises(Exception):
        Profile.model_validate({'entities': [entity]})


def test_names_are_trimmed_and_never_match_a_line_without_the_name():
    profile = Profile.model_validate({'entities': [{'canonical': ' RIKU ', 'aliases': [' 리쿠 ']}]})
    assert profile.entities[0].canonical == 'RIKU' and profile.entities[0].aliases == ['리쿠']
    assert profile.mentions('Nobody is named here.') == ()
