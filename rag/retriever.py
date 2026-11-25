"""Per-version hybrid retrieval.

For each release on its own: BM25 and dense search each return candidates, the two
lists are merged with reciprocal rank fusion, and a cross-encoder reranks the
merged list. Running each version separately means one release can never crowd the
other out of the results, which is the whole point when they disagree.

Try it:  python -m rag.retriever "How far can the kubelet lag behind the API server?"
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import faiss
import numpy as np
from rank_bm25 import BM25Okapi

from rag.chunker import Chunk

Mode = Literal["bm25", "dense", "hybrid", "hybrid_rerank"]
QueryEmbedFn = Callable[[str], np.ndarray]
RerankFn = Callable[[str, Sequence[str]], Sequence[float]]

CANDIDATES = 30  # per retriever, per version, before fusion
RERANK_POOL = 10  # fused candidates sent to the cross-encoder, per version
RRF_K = 60  # standard constant from the RRF paper
TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*")
STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for",
        "from", "how", "i", "in", "is", "it", "of", "on", "or", "the", "to", "what",
        "when", "where", "which", "who", "why", "will", "with", "you", "your",
    }
)  # fmt: skip


def tokenize(text: str) -> list[str]:
    """Lowercase tokens that keep flags and dotted names whole (max-pods, v1.31)."""
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


def canonical_doc(doc_id: str, aliases: dict[str, str]) -> str:
    """Pages that moved between releases share one id for pairing."""
    return aliases.get(doc_id, doc_id)


@dataclass(frozen=True)
class Hit:
    """A retrieved chunk and the score that ranked it."""

    chunk: Chunk
    score: float


@dataclass
class Retrieval:
    """Results per version, plus the same hits grouped by page across versions."""

    by_version: dict[str, list[Hit]]
    pairs: dict[str, dict[str, list[Hit]]] = field(default_factory=dict)

    def all_hits(self) -> list[Hit]:
        """Every hit, best first."""
        hits = [h for hs in self.by_version.values() for h in hs]
        return sorted(hits, key=lambda h: (-h.score, h.chunk.chunk_id))

    def chunk_ids(self) -> list[str]:
        """Ids in rank order, as returned in `retrieved_chunk_ids`."""
        return [h.chunk.chunk_id for h in self.all_hits()]

    def top_score(self) -> float:
        """Best score across versions; the refusal gate reads this."""
        return max((h.score for h in self.all_hits()), default=0.0)


class _VersionIndex:
    """FAISS + BM25 over one release."""

    def __init__(self, index_dir: Path, version: str, chunks: dict[str, Chunk]) -> None:
        self.ids: list[str] = json.loads((index_dir / f"{version}.ids.json").read_text())
        self.faiss = faiss.read_index(str(index_dir / f"{version}.faiss"))
        self.bm25 = BM25Okapi([tokenize(chunks[i].embed_text()) for i in self.ids])

    def bm25_top(self, query: str, n: int) -> list[str]:
        """Top-n chunk ids by BM25; chunks with no term overlap are left out."""
        scores = self.bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))[:n]
        return [self.ids[i] for i in order if scores[i] > 0]

    def dense_top(self, vector: np.ndarray, n: int) -> list[tuple[str, float]]:
        """Top-n chunk ids by cosine similarity (vectors are unit length)."""
        scores, rows = self.faiss.search(vector.reshape(1, -1).astype("float32"), n)
        return [(self.ids[r], float(s)) for s, r in zip(scores[0], rows[0], strict=True) if r >= 0]


def rrf(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal rank fusion: sum of 1/(k + rank) over every list an id appears in."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


class Retriever:
    """Loads index/ once and answers retrieval calls."""

    def __init__(
        self, index_dir: Path, embed_query: QueryEmbedFn, rerank: RerankFn | None = None
    ) -> None:
        self.embed_query = embed_query
        self.rerank = rerank
        self.chunks: dict[str, Chunk] = {}
        with (index_dir / "chunks.jsonl").open(encoding="utf-8") as fh:
            for line in fh:
                chunk = Chunk(**json.loads(line))
                self.chunks[chunk.chunk_id] = chunk
        self.versions = sorted({c.version for c in self.chunks.values()})
        self.aliases: dict[str, str] = json.loads((index_dir / "doc_aliases.json").read_text())
        self.indexes = {v: _VersionIndex(index_dir, v, self.chunks) for v in self.versions}

    def _search_version(
        self, query: str, vector: np.ndarray | None, version: str, top_k: int, mode: Mode
    ) -> list[Hit]:
        index = self.indexes[version]
        if mode == "bm25":
            ranked = [
                (cid, 1.0 / (RRF_K + r)) for r, cid in enumerate(index.bm25_top(query, top_k), 1)
            ]
        elif mode == "dense":
            assert vector is not None
            ranked = index.dense_top(vector, top_k)
        else:
            assert vector is not None
            dense_ids = [cid for cid, _ in index.dense_top(vector, CANDIDATES)]
            ranked = rrf([index.bm25_top(query, CANDIDATES), dense_ids])
        if mode == "hybrid_rerank" and self.rerank is not None:
            pool = [cid for cid, _ in ranked[:RERANK_POOL]]
            scores = self.rerank(query, [self.chunks[c].embed_text() for c in pool])
            ranked = sorted(zip(pool, scores, strict=True), key=lambda kv: (-kv[1], kv[0]))
        return [Hit(self.chunks[cid], float(score)) for cid, score in ranked[:top_k]]

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        version: str | None = None,
        mode: Mode = "hybrid_rerank",
    ) -> Retrieval:
        """Top-k per version (or for one pinned version), grouped by page."""
        versions = [version] if version in self.versions else self.versions
        vector = None if mode == "bm25" else self.embed_query(query)
        by_version = {v: self._search_version(query, vector, v, top_k, mode) for v in versions}

        pairs: dict[str, dict[str, list[Hit]]] = {}
        for v, hits in by_version.items():
            for hit in hits:
                doc = canonical_doc(hit.chunk.doc_id, self.aliases)
                pairs.setdefault(doc, {}).setdefault(v, []).append(hit)
        return Retrieval(by_version=by_version, pairs=pairs)


BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def load_default_retriever(index_dir: Path) -> Retriever:
    """Wire the real models in. Kept out of __init__ so tests can inject fakes."""
    # pylint: disable=import-outside-toplevel
    from rag.models import get_embedder, get_reranker

    embedder, reranker = get_embedder(), get_reranker()

    def embed_query(text: str) -> np.ndarray:
        return np.asarray(embedder.encode(BGE_QUERY_PREFIX + text, normalize_embeddings=True))

    def rerank(query: str, texts: Sequence[str]) -> list[float]:
        raw = [float(x) for x in reranker.predict([(query, t) for t in texts])]
        # Recent sentence-transformers already apply a sigmoid to single-label
        # cross-encoders. Only squash if we were handed raw logits.
        if all(0.0 <= x <= 1.0 for x in raw):
            return raw
        return [1.0 / (1.0 + math.exp(-x)) for x in raw]

    return Retriever(index_dir, embed_query, rerank)


def main() -> None:
    """Print the top hits for a question, to eyeball retrieval by hand."""
    from app.config import settings  # pylint: disable=import-outside-toplevel

    query = " ".join(sys.argv[1:]) or "How many minor versions may the kubelet lag behind?"
    result = load_default_retriever(settings.index_dir).retrieve(query)
    for version, hits in result.by_version.items():
        print(f"\n== {version}")
        for hit in hits:
            print(f"  {hit.score:.3f}  {hit.chunk.chunk_id}  | {hit.chunk.section[:60]}")


if __name__ == "__main__":
    main()
