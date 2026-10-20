"""Typed labels with explicit draft/unknown status; no invented video truth."""

import json
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Question(BaseModel):
    id: str
    query: str = Field(min_length=1)
    split: Literal['dev','gold_draft','gold']
    category: str
    answerability: Literal['scene_supported','multiple_scenes','speaker_unknown',
                           'visual_unsupported','not_found','pending_not_found']
    expected_video_id: str | None
    accepted_intervals: list[tuple[float,float]]
    evidence_cue_ids: list[str]
    expected_speaker_status: Literal['unknown'] = 'unknown'
    label_status: Literal['draft','accepted'] = 'draft'

    @model_validator(mode='after')
    def check_labels(self):
        for start,end in self.accepted_intervals:
            if not (math.isfinite(start) and math.isfinite(end) and 0<=start<end):
                raise ValueError('Invalid accepted interval')
        if self.scene_answerable:
            if not self.expected_video_id or not self.accepted_intervals or not self.evidence_cue_ids:
                raise ValueError('Scene labels require video, intervals and source cue IDs')
        elif self.accepted_intervals or self.evidence_cue_ids or self.expected_video_id:
            raise ValueError('Unsupported/negative labels cannot invent source evidence')
        return self

    @property
    def scene_answerable(self):
        return self.answerability in {'scene_supported','multiple_scenes','speaker_unknown'}


def load_questions(path: Path) -> list[Question]:
    rows=[Question.model_validate(json.loads(line)) for line in path.read_text().splitlines() if line.strip()]
    if not rows or len({r.id for r in rows})!=len(rows):
        raise ValueError('Dataset must be nonempty with unique IDs')
    return rows


def validate_source_labels(rows, catalog):
    """Check source IDs/interval membership, not actual video timing or meaning."""
    for row in rows:
        if not row.scene_answerable:
            continue
        cues={c.cue_id:c for c in catalog.cues.get(row.expected_video_id,[])}
        for cue_id in row.evidence_cue_ids:
            cue=cues.get(cue_id)
            if cue is None or not any(start<=cue.start_seconds and cue.end_seconds<=end
                                      for start,end in row.accepted_intervals):
                raise ValueError(f'Invalid source label: {row.id}:{cue_id}')
        for start, end in row.accepted_intervals:
            if not any(start <= cues[cue_id].start_seconds and cues[cue_id].end_seconds <= end
                       for cue_id in row.evidence_cue_ids):
                raise ValueError(f'Unbacked accepted interval: {row.id}:{start}-{end}')
