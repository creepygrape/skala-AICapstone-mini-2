"""Local BM25 + multilingual dense retrieval, shared by JSON and MCP."""

import hashlib
import json
import os
from pathlib import Path
import re

import numpy as np
from rank_bm25 import BM25Plus

from backend.app.retrieval.chunker import make_chunks
from backend.app.schemas import Candidate, SearchReply


def tokens(text: str):
    return re.findall(r"[\w]+", text.casefold())


class LocalEncoder:
    """Only load a complete existing local model snapshot; never download."""
    def __init__(self, path: str | None = None):
        import torch
        from sentence_transformers import SentenceTransformer
        torch.set_num_threads(4)
        if path:
            location = Path(path).expanduser()
        else:
            cache = Path.home() / ".cache/huggingface/hub/models--BAAI--bge-m3/snapshots"
            available = sorted(p for p in cache.glob("*") if (p / "modules.json").exists()
                               and ((p / "model.safetensors").exists() or (p / "pytorch_model.bin").exists()))
            if not available:
                raise RuntimeError("No complete local bge-m3 cache; model download is disabled")
            location = available[-1]
        self.identity = str(location.resolve())
        self.model = SentenceTransformer(str(location), local_files_only=True, device="cpu")

    def encode(self, texts):
        return self.model.encode(texts, batch_size=8, normalize_embeddings=True,
                                 show_progress_bar=False, convert_to_numpy=True)


class Retriever:
    def __init__(self, catalog, encoder=None, cache_dir: Path | None = None, *, chunk_window: int = 20, chunk_stride: int = 10):
        self.catalog = catalog
        self.chunk_window, self.chunk_stride = chunk_window, chunk_stride
        self.cue_maps = {video_id: {c.cue_id: c for c in cues}
                         for video_id, cues in catalog.cues.items()}
        self.chunks = make_chunks([c for group in catalog.cues.values() for c in group], chunk_window, chunk_stride)
        self.tokenized = [tokens(c.text_for_retrieval) or [""] for c in self.chunks]
        self.keyword = BM25Plus(self.tokenized)
        self.encoder, self.vectors = encoder, None
        self.cue_vectors = {}
        if encoder:
            source = [(c.chunk_id, c.cue_ids, c.text_for_retrieval) for c in self.chunks]
            digest = hashlib.sha256(json.dumps([encoder.identity, source], ensure_ascii=False).encode()).hexdigest()
            path = cache_dir / f"{digest}.npy" if cache_dir else None
            if path and path.exists():
                self.vectors = np.load(path, allow_pickle=False)
            else:
                self.vectors = encoder.encode([c.text_for_retrieval for c in self.chunks])
                if path:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = path.with_suffix(".tmp")
                    with temporary.open("wb") as f:
                        np.save(f, self.vectors, allow_pickle=False)
                    temporary.replace(path)
            if self.vectors.ndim != 2 or len(self.vectors) != len(self.chunks):
                raise ValueError("Dense index shape mismatch")

    def search(self, query: str, mode="hybrid", top_k=3, video_ids=None) -> SearchReply:
        if mode not in {"keyword", "dense", "hybrid"} or not 1 <= top_k <= 20:
            raise ValueError("Invalid retrieval mode or top_k")
        if video_ids and not set(video_ids) <= self.catalog.videos.keys():
            raise ValueError("Unknown video ID")
        if mode != "keyword" and self.encoder is None:
            raise RuntimeError("Dense index is not available")
        allowed = [i for i,c in enumerate(self.chunks) if not video_ids or c.video_id in video_ids]
        ranks = []
        if mode != "dense":
            scores = self.keyword.get_scores(tokens(query))
            query_tokens = set(tokens(query))
            ranks.append(sorted((i for i in allowed if query_tokens.intersection(self.tokenized[i])), key=lambda i: (-scores[i], i))[:20])
        if mode != "keyword":
            vector = self.encoder.encode([query])[0]
            scores = self.vectors @ vector
            ranks.append(sorted(allowed, key=lambda i: (-scores[i], i))[:20])
        fused = {}
        for rank in ranks:
            for position,i in enumerate(rank,1):
                fused[i] = fused.get(i,0) + 1/(60+position)
        result = []
        for i in sorted(fused, key=lambda i: (-fused[i], i)):
            chunk = self.chunks[i]
            if any(old.chunk.video_id == chunk.video_id and
                   (set(old.chunk.cue_ids) & set(chunk.cue_ids) or
                    abs(old.chunk.start_seconds-chunk.start_seconds)<10) for old in result):
                continue
            candidate = Candidate(chunk=chunk, score=fused[i])
            # Reuse this request's vector. Keyword mode never invokes dense.
            candidate.selected_cue_id = self.select_cue(
                query, candidate, query_vector=vector if mode != "keyword" else None,
                use_dense=mode != "keyword"
            ).cue_id
            result.append(candidate)
            if len(result) >= top_k:
                break
        return SearchReply(candidates=result, mode=mode)

    def select_cue(self, query, candidate, query_vector=None, use_dense=True):
        chunk = candidate.chunk
        cue_map = self.cue_maps[chunk.video_id]
        cues = [cue_map[i] for i in chunk.cue_ids]
        if not self.encoder or not use_dense:
            query_tokens = set(tokens(query))
            return max(cues, key=lambda c: len(query_tokens & set(tokens(c.original_text))))
        missing = [c for c in cues if (c.video_id,c.cue_id) not in self.cue_vectors]
        if missing:
            encoded = self.encoder.encode([c.original_text for c in missing])
            for c,vector in zip(missing,encoded):
                self.cue_vectors[c.video_id,c.cue_id] = vector
        q = query_vector if query_vector is not None else self.encoder.encode([query])[0]
        return max(cues,key=lambda c:float(self.cue_vectors[c.video_id,c.cue_id] @ q))
