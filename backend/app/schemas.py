"""Shared source, tool and API contracts. Speakers are unknown in this corpus."""

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from backend.app.services.urls import video_url


class Cue(BaseModel):
    model_config = ConfigDict(frozen=True)
    video_id: str
    cue_id: str
    start_seconds: float
    end_seconds: float
    original_text: str
    speaker: None = None
    mentioned_members: tuple[str, ...] = ()
    caption_type: Literal["dialogue", "editorial", "mixed", "unknown"] = "unknown"


class Chunk(BaseModel):
    chunk_id: str
    video_id: str
    cue_ids: tuple[str, ...]
    start_seconds: float
    end_seconds: float
    text_for_retrieval: str
    long_cue: bool = False


class Video(BaseModel):
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    title: str
    transcript_file: str = Field(exclude=True)
    language: str = "en"
    license_or_source_note: str = "사용자 제공 로컬 자막. 이용 조건 확인 필요."
    title_verified: bool = False
    timing_verified: bool = Field(default=False, description="사용자의 일부 시점 표본 확인. 전체 cue 검증 아님.")

    @property
    def url(self):
        return video_url(self.video_id)


class Candidate(BaseModel):
    chunk: Chunk
    score: float
    selected_cue_id: str | None = None


class SearchReply(BaseModel):
    candidates: list[Candidate]
    mode: Literal["keyword", "dense", "hybrid"]


class ContextReply(BaseModel):
    video_id: str
    cues: list[Cue]


class NeighborsReply(BaseModel):
    """Source cues around one cue, in video order and never crossing videos."""
    video_id: str
    target_cue_id: str
    cues: list[Cue]


class MetadataReply(BaseModel):
    video_id: str
    title: str
    url: str
    title_verified: bool
    timing_verified: bool = Field(description="사용자의 일부 시점 표본 확인. 전체 cue 검증 아님.")


class HistoryTop(BaseModel):
    video_id: str = Field(max_length=32)
    title: str = Field(max_length=200)
    start_seconds: float = Field(ge=0)
    evidence_text: str = Field(max_length=120)


class HistoryTurn(BaseModel):
    """Compact previous turn: only used to resolve references in a follow-up, never as evidence."""
    query: str = Field(min_length=1, max_length=300)
    top: HistoryTop | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    thread_id: str | None = Field(default=None, max_length=128)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=3)
    exclude: list[Annotated[str, Field(max_length=64)]] = Field(
        default_factory=list, max_length=20, description='이미 보여 준 "video_id:cue_id" 키')

    @field_validator("query")
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("질문을 입력해 주세요.")
        return value


class SceneResult(BaseModel):
    video_id: str
    title: str
    cue_ids: list[str]
    start_seconds: float
    end_seconds: float
    url: str
    evidence_text: str
    evidence_type: str
    speaker: None = None
    speaker_status: Literal["unknown"] = "unknown"
    explanation_ko: str


class SearchResponse(BaseModel):
    request_id: str
    status: Literal["found", "ambiguous", "not_found", "unsupported", "partial", "error"]
    search_attempts: int = Field(ge=0, le=3)
    results: list[SceneResult] = []
    warnings: list[str] = []
