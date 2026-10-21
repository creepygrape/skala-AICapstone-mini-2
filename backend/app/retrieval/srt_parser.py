"""Strict SRT parsing. Preserve cue text; never infer a speaker."""

import re
from pathlib import Path
from backend.app.schemas import Cue

TIME = r"(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})"
STAMP = re.compile(rf"^{TIME} --> {TIME}$")


def parse_srt(path: Path, video_id: str, find_mentions=None) -> list[Cue]:
    """Read UTF-8/BOM SRT. Raise ValueError on malformed/duplicate/invalid cues.

    find_mentions (e.g. Profile.mentions) fills mentioned_members; it is never a speaker.

    Overlap and repeated text are valid. Normalizes only file line endings.
    """
    source = path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    cues, ids = [], set()
    for block in re.split(r"\n(?:[ \t]*\n)+", source.strip("\n")):
        lines = block.split("\n")
        # Normalize structural fields only, never strip original caption text.
        if len(lines) >= 2:
            lines[0], lines[1] = lines[0].strip(), lines[1].strip()
        if len(lines) < 3 or not lines[0].isdigit():
            raise ValueError(f"Invalid SRT block in {path.name}")
        match = STAMP.fullmatch(lines[1])
        if not match or lines[0] in ids:
            raise ValueError(f"Invalid timestamp or duplicate cue {lines[0]}")
        values = list(map(int, match.groups()))
        def seconds(parts):
            h, m, s, ms = parts
            return h * 3600 + m * 60 + s + ms / 1000
        start, end = seconds(values[:4]), seconds(values[4:])
        text = "\n".join(lines[2:])
        if end <= start or not text.strip():
            raise ValueError(f"Invalid duration/text in cue {lines[0]}")
        if cues and start < cues[-1].start_seconds:
            raise ValueError(f"Out-of-order cue {lines[0]}")
        # Parentheses may be explanations, so do not classify them automatically.
        editorial = bool(re.search(r"\([^)]*\bchose\b[^)]*\)", text, re.I))
        remainder = re.sub(r"\([^)]*\)", "", text).strip()
        kind = ("mixed" if remainder else "editorial") if editorial else "unknown"
        cues.append(Cue(video_id=video_id, cue_id=lines[0], start_seconds=start,
                        end_seconds=end, original_text=text,
                        mentioned_members=find_mentions(text) if find_mentions else (),
                        caption_type=kind))
        ids.add(lines[0])
    if not cues:
        raise ValueError("Empty transcript")
    return cues
