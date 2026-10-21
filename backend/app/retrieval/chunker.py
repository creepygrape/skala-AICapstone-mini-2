"""Video-local 20s windows at 10s stride with immutable cue references."""

import os
from collections import defaultdict
from backend.app.schemas import Chunk, Cue


DEFAULT_WINDOW, DEFAULT_STRIDE, MAX_WINDOW = 20, 10, 120


def chunk_settings(environ=None) -> tuple[int, int]:
    """Chunk window and stride in seconds, from WISH_CHUNK_WINDOW / WISH_CHUNK_STRIDE (default 20 / 10).

    The defaults are a design assumption that was never compared with other values; these variables
    exist so that comparison can be run (eval/README.md). Invalid values fail at start-up.
    """
    environ = os.environ if environ is None else environ
    values = []
    for name, default in (("WISH_CHUNK_WINDOW", DEFAULT_WINDOW), ("WISH_CHUNK_STRIDE", DEFAULT_STRIDE)):
        raw = environ.get(name)
        try:
            values.append(default if raw in (None, "") else int(raw))
        except ValueError:
            raise ValueError(f"{name} must be an integer number of seconds, got {raw!r}") from None
    window, stride = values
    if not 0 < stride <= window <= MAX_WINDOW:
        raise ValueError(f"Require 0 < WISH_CHUNK_STRIDE <= WISH_CHUNK_WINDOW <= {MAX_WINDOW}, got stride={stride}, window={window}")
    return window, stride


def make_chunks(cues: list[Cue], window: int = 20, stride: int = 10) -> list[Chunk]:
    """Group by cue start, isolate long cues, preserve all source references."""
    if not 0 < stride <= window:
        raise ValueError("Require 0 < stride <= window")
    groups = defaultdict(list)
    for cue in cues:
        if cue.end_seconds - cue.start_seconds > window:
            groups[(cue.video_id, f"long-{cue.cue_id}")].append(cue)
            continue
        last = int(cue.start_seconds // stride)
        for index in range(max(0, int((cue.start_seconds - window) // stride) + 1), last + 1):
            groups[(cue.video_id, str(index))].append(cue)
    result, seen = [], set()
    for (video_id, key), items in groups.items():
        ids = tuple(c.cue_id for c in items)
        if (video_id, ids) in seen:
            continue
        seen.add((video_id, ids))
        texts = []
        for index, cue in enumerate(items):
            text = cue.original_text
            if index:
                previous = items[index-1].original_text
                if text.startswith(previous):
                    suffix = text[len(previous):]
                    # Whitespace or an exact repetition is safe. Punctuation
                    # alone is not: "we" + "we're" must preserve the word.
                    if not suffix or suffix[0].isspace():
                        text = suffix.lstrip()
            texts.append(text)
        result.append(Chunk(chunk_id=f"{video_id}:{key}", video_id=video_id, cue_ids=ids,
                            start_seconds=min(c.start_seconds for c in items),
                            end_seconds=max(c.end_seconds for c in items),
                            text_for_retrieval="\n".join(t for t in texts if t), long_cue=key.startswith("long-")))
    return sorted(result, key=lambda c: (c.video_id, c.start_seconds, c.chunk_id))
