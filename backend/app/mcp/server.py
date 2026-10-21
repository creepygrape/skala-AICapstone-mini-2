"""Read-only transcript tools on the official SDK 2.x MCPServer."""

from functools import lru_cache
import os
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from backend.app.schemas import ContextReply, MetadataReply, NeighborsReply, SearchReply
from backend.app.profile import load_profile
from backend.app.services.video_catalog import Catalog, ROOT
from backend.app.retrieval.chunker import chunk_settings
from backend.app.retrieval.hybrid import LocalEncoder, Retriever
from backend.app.mcp.search_gate import SearchGate

server = MCPServer("wish-finder", instructions="Read-only transcript search. Never infer speakers.")
search_gate = SearchGate()


@lru_cache(maxsize=1)
def resources():
    catalog = Catalog(profile=load_profile())
    encoder = None if os.getenv("WISH_KEYWORD_ONLY") == "1" else LocalEncoder(os.getenv("WISH_EMBEDDING_PATH"))
    window, stride = chunk_settings()
    return catalog, Retriever(catalog, encoder, ROOT / "data/index", chunk_window=window, chunk_stride=stride)


@server.tool(structured_output=True)
def search_transcripts(query: Annotated[str, Field(min_length=1,max_length=1000)],
                       mode: Literal["hybrid","keyword","dense"] = "hybrid",
                       top_k: Annotated[int, Field(ge=1,le=20)] = 3,
                       video_ids: list[str] | None = None) -> SearchReply:
    """Search registered transcripts. Returns cue-linked candidates, not answers.

    Raises an MCP tool error for unknown videos, invalid input or unavailable dense index.
    Empty matches are returned as an empty candidates list.
    """
    with search_gate.acquire():
        _,retriever = resources()
        return retriever.search(query,mode,top_k,video_ids)


@server.tool(structured_output=True)
def get_scene_context(video_id: str, start_seconds: Annotated[float, Field(ge=0)],
                      window_seconds: Annotated[int, Field(ge=1,le=60)] = 20) -> ContextReply:
    """Return chronological exact source cues intersecting a forward time window.

    Unknown video IDs raise a tool error; callers cannot choose a file path.
    """
    catalog,_ = resources()
    return ContextReply(video_id=video_id,cues=catalog.context(video_id,start_seconds,window_seconds))


@server.tool(structured_output=True)
def get_cue_neighbors(video_id: str, cue_id: str,
                      before: Annotated[int, Field(ge=0, le=5)] = 3,
                      after: Annotated[int, Field(ge=0, le=5)] = 3) -> NeighborsReply:
    """Return exact source cues before and after one cue of the same video.

    Unknown video or cue IDs raise a tool error; the window never crosses videos.
    """
    catalog,_ = resources()
    return NeighborsReply(video_id=video_id,target_cue_id=cue_id,
                          cues=catalog.neighbors(video_id,cue_id,before,after))


@server.tool(structured_output=True)
def get_video_metadata(video_id: str) -> MetadataReply:
    """Read registered video title and URL; unknown IDs raise a tool error."""
    catalog,_ = resources()
    if video_id not in catalog.videos:
        raise ValueError("Unknown video ID")
    v = catalog.videos[video_id]
    return MetadataReply(video_id=v.video_id,title=v.title,url=v.url,
                         title_verified=v.title_verified,timing_verified=v.timing_verified)


if __name__ == "__main__":
    resources()
    server.run(transport="stdio")
