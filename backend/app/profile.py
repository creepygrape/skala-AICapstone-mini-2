"""Collection profile: what the subtitles are about, in which language, and known names.

The profile keeps collection-specific knowledge (names, languages, translation notes) out
of the code and prompts so the same pipeline can serve another collection. Everything has
a default, so a missing profile file simply means "generic collection".
"""

import json
import os
from pathlib import Path
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = 'data/profile.local.json'


class Entity(BaseModel):
    model_config = ConfigDict(extra='forbid')
    canonical: str = Field(min_length=1, max_length=40)
    aliases: list[str] = Field(default_factory=list, max_length=10)

    @field_validator('canonical')
    @classmethod
    def _canonical_not_blank(cls, value):
        # A blank form would match every subtitle line in Profile.mentions().
        value = value.strip()
        if not value:
            raise ValueError('canonical must not be blank')
        return value

    @field_validator('aliases')
    @classmethod
    def _aliases_not_blank(cls, values):
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 40 for value in cleaned):
            raise ValueError('aliases must be 1-40 characters after trimming')
        return cleaned


class Profile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(default='the transcript collection', max_length=80)
    subtitle_language: str = Field(default='English', max_length=40)
    speech_languages: list[str] = Field(default_factory=list, max_length=6)
    translated: bool = False
    entities: list[Entity] = Field(default_factory=list, max_length=60)
    notes: str = Field(default='', max_length=500)

    def render(self):
        """Short prompt section. Trusted local configuration, never user input."""
        lines = [f'Collection: {self.name}.', f'Subtitle language: {self.subtitle_language}.']
        if self.translated:
            spoken = ' and '.join(self.speech_languages) or 'the spoken language'
            lines.append(f'The subtitles are translated from {spoken}: wording can differ from what '
                         'the user remembers, parenthesized text may be translator or editor notes, '
                         'and foreign words may appear romanized.')
        if self.entities:
            names = '; '.join(f"{e.canonical} = {', '.join(e.aliases)}" if e.aliases else e.canonical
                              for e in self.entities)
            lines.append(f'Known names (write the spelling before "=" in queries): {names}.')
        if self.notes:
            lines.append(self.notes)
        return '\n'.join(lines)

    def mentions(self, text):
        """Known names appearing as whole words in a subtitle line (never a speaker)."""
        found = set()
        for entity in self.entities:
            for form in (entity.canonical, *entity.aliases):
                # Latin names need word boundaries (RYO is not "ryokan"); Korean/Japanese forms
                # take particles ("리쿠가"), so they match as substrings.
                hit = (re.search(rf'(?<!\w){re.escape(form)}(?!\w)', text, re.I) if form.isascii()
                       else form in text)
                if hit:
                    found.add(entity.canonical.upper())
                    break
        return tuple(sorted(found))


def load_profile(path=None):
    """Read the profile from WISH_PROFILE (default data/profile.local.json).

    A missing file means the generic default; an unreadable or invalid file fails fast so a
    typo cannot silently degrade the prompts. Only files under data/ are accepted.
    """
    location = Path(path or os.getenv('WISH_PROFILE') or DEFAULT_PATH)
    location = (location if location.is_absolute() else ROOT / location).resolve()
    if not location.is_relative_to((ROOT / 'data').resolve()):
        raise ValueError('Profile must be under data/')
    if not location.exists():
        return Profile()
    return Profile.model_validate(json.loads(location.read_text(encoding='utf-8')))
