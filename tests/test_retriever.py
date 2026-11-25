"""Retrieval runs per version and pairs pages across versions."""

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from rag.ingest import build_index
from rag.retriever import Retriever, rrf, tokenize
from tests.test_ingest import fake_embed

SKEW_127 = "---\ntitle: Skew\n---\n## kubelet\nThe kubelet may be up to two minor versions older.\n"
SKEW_131 = (
    "---\ntitle: Skew\n---\n## kubelet\nThe kubelet may be up to three minor versions older.\n"
)
OTHER = "---\ntitle: Jobs\n---\n## Retries\nThe backoffLimit field sets how many retries happen.\n"


@pytest.fixture(name="retriever")
def retriever_fixture(tmp_path: Path) -> Retriever:
    corpus = tmp_path / "corpus"
    for version, skew in (("1.27", SKEW_127), ("1.31", SKEW_131)):
        (corpus / version / "releases").mkdir(parents=True)
        (corpus / version / "releases" / "skew.md").write_text(skew)
        (corpus / version / "releases" / "jobs.md").write_text(OTHER)
        for i in range(4):  # BM25 needs a few unrelated pages for IDF to mean anything
            filler = (
                f"---\ntitle: Filler {i}\n---\n## Topic\n"
                f"Unrelated text about item {i}, long enough to be kept as a chunk.\n"
            )
            (corpus / version / "releases" / f"filler{i}.md").write_text(filler)
    build_index(corpus, tmp_path / "index", fake_embed)

    def rerank(query: str, texts: Sequence[str]) -> list[float]:
        words = set(tokenize(query))
        return [len(words & set(tokenize(t))) / 10 for t in texts]

    return Retriever(tmp_path / "index", lambda q: fake_embed([q])[0], rerank)


def test_both_versions_are_searched(retriever: Retriever) -> None:
    result = retriever.retrieve("kubelet minor versions older", top_k=1)
    assert set(result.by_version) == {"1.27", "1.31"}
    assert result.pairs["releases/skew"].keys() == {"1.27", "1.31"}


def test_version_filter_pins_one_release(retriever: Retriever) -> None:
    result = retriever.retrieve("kubelet", top_k=2, version="1.31")
    assert set(result.by_version) == {"1.31"}


def test_reranker_orders_results(retriever: Retriever) -> None:
    hits = retriever.retrieve("kubelet minor versions older", top_k=2).by_version["1.31"]
    assert hits[0].chunk.doc_id == "releases/skew"
    assert hits[0].score >= hits[1].score


def test_every_mode_runs(retriever: Retriever) -> None:
    for mode in ("bm25", "dense", "hybrid", "hybrid_rerank"):
        assert retriever.retrieve("retries backoffLimit", top_k=1, mode=mode).chunk_ids()


def test_rrf_rewards_agreement() -> None:
    fused = dict(rrf([["a", "b"], ["b", "c"]]))
    assert fused["b"] > fused["a"] > fused["c"]


def test_tokenize_keeps_flags_whole() -> None:
    assert "max-pods" in tokenize("Set --max-pods on the kubelet")
    assert "the" not in tokenize("the kubelet")


def test_empty_vector_space_is_safe(retriever: Retriever) -> None:
    result = retriever.retrieve("zzzz qqqq", top_k=3, mode="bm25")
    assert result.top_score() == 0.0 or isinstance(result.top_score(), float)
    assert np.isfinite(result.top_score())
