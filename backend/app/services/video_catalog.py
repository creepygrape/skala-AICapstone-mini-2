"""Manifest-only file access: users cannot submit arbitrary file paths."""

import json
from pathlib import Path
from backend.app.schemas import Video
from backend.app.retrieval.srt_parser import parse_srt

ROOT = Path(__file__).resolve().parents[3]


def load_videos(manifest: Path | None = None) -> list[Video]:
    """Read only registered metadata; does not load transcripts or models."""
    path = manifest or ROOT / "data/manifest.local.json"
    return [Video.model_validate(row) for row in json.loads(path.read_text())]


class Catalog:
    def __init__(self, manifest: Path | None = None):
        self.videos, self.cues = {}, {}
        for video in load_videos(manifest):
            if video.video_id in self.videos:
                raise ValueError("Duplicate video ID")
            source = (ROOT / video.transcript_file).resolve()
            if not source.is_relative_to((ROOT / "data").resolve()):
                raise ValueError("Transcript must be under data/")
            self.videos[video.video_id] = video
            self.cues[video.video_id] = parse_srt(source, video.video_id)
        if not self.videos:
            raise ValueError("Empty catalog")

    def context(self, video_id: str, start: float, window: int):
        if video_id not in self.videos:
            raise ValueError("Unknown video ID")
        return [c for c in self.cues[video_id] if c.start_seconds < start + window and c.end_seconds > start]
