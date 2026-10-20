"""Canonical YouTube links from validated source IDs and cue start times."""

import math
import re


def video_url(video_id: str, start_seconds: float | None = None) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Invalid video ID")
    base = f"https://www.youtube.com/watch?v={video_id}"
    if start_seconds is None:
        return base
    if not math.isfinite(start_seconds) or start_seconds < 0:
        raise ValueError("Invalid start time")
    return f"{base}&t={math.floor(start_seconds)}s"
