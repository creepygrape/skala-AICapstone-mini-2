"""Manifest-only file access: users cannot submit arbitrary file paths."""

import json
import os
from pathlib import Path
from backend.app.schemas import Video
from backend.app.retrieval.srt_parser import parse_srt

ROOT = Path(__file__).resolve().parents[3]


def resolve_manifest(manifest: Path | str | None = None) -> Path:
    """Resolve API and subprocess manifest paths against the same project root."""
    path = Path(manifest or os.getenv("WISH_MANIFEST") or "data/manifest.local.json")
    return (path if path.is_absolute() else ROOT / path).resolve()


def load_videos(manifest: Path | None = None) -> list[Video]:
    """Read only registered metadata; does not load transcripts or models."""
    path = resolve_manifest(manifest)
    return [Video.model_validate(row) for row in json.loads(path.read_text(encoding="utf-8"))]


class Catalog:
    def __init__(self, manifest: Path | None = None, profile=None):
        self.videos, self.cues = {}, {}
        find_mentions = profile.mentions if profile else None
        for video in load_videos(manifest):
            if video.video_id in self.videos:
                raise ValueError("Duplicate video ID")
            source = (ROOT / video.transcript_file).resolve()
            if not source.is_relative_to((ROOT / "data").resolve()):
                raise ValueError("Transcript must be under data/")
            self.videos[video.video_id] = video
            self.cues[video.video_id] = parse_srt(source, video.video_id, find_mentions)
        if not self.videos:
            raise ValueError("Empty catalog")

    def context(self, video_id: str, start: float, window: int):
        if video_id not in self.videos:
            raise ValueError("Unknown video ID")
        return [c for c in self.cues[video_id] if c.start_seconds < start + window and c.end_seconds > start]

    def neighbors(self, video_id: str, cue_id: str, before: int, after: int):
        """Cues around `cue_id` from the same video, clamped at the video boundaries."""
        if video_id not in self.videos:
            raise ValueError("Unknown video ID")
        cues = self.cues[video_id]
        index = next((i for i, c in enumerate(cues) if c.cue_id == cue_id), None)
        if index is None:
            raise ValueError("Unknown cue ID")
        return cues[max(0, index - before): index + after + 1]
