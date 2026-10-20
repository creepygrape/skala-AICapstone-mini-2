"""Deterministic evidence construction. No LLM-created quote, time or speaker."""

from backend.app.schemas import Candidate, ContextReply, MetadataReply, SceneResult
from backend.app.services.urls import video_url


def verify_candidate(candidate: Candidate, context: ContextReply, video: MetadataReply) -> SceneResult:
    """Resolve a selected cue inside returned source context or raise ValueError."""
    chunk = candidate.chunk
    if not chunk.video_id == context.video_id == video.video_id:
        raise ValueError("Evidence video mismatch")
    if candidate.selected_cue_id not in chunk.cue_ids:
        raise ValueError("Evidence outside candidate")
    cue = next((c for c in context.cues if c.cue_id == candidate.selected_cue_id),None)
    if cue is None or cue.video_id != chunk.video_id:
        raise ValueError("Source cue missing")
    if not 0 <= chunk.start_seconds <= cue.start_seconds < cue.end_seconds <= chunk.end_seconds:
        raise ValueError("Invalid evidence timestamps")
    if not cue.original_text.strip() or cue.speaker is not None:
        raise ValueError("Invalid source quote or unsupported speaker")
    return SceneResult(video_id=cue.video_id,title=video.title,cue_ids=[cue.cue_id],
                       start_seconds=cue.start_seconds,end_seconds=cue.end_seconds,
                       url=video_url(cue.video_id, cue.start_seconds),
                       evidence_text=cue.original_text,evidence_type=cue.caption_type,
                       explanation_ko="검색된 원문 자막 구간입니다. 질문과의 의미 일치는 아직 검증하지 않았습니다.")
