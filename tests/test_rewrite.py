"""Query rewrite: only for weak searches, and merged so nothing found is lost."""

from __future__ import annotations

from rag.chunker import Chunk
from rag.retriever import Hit, Retrieval, Retriever
from rag.rewrite import retrieve_with_rewrite


def hit(cid: str, score: float, version: str = "1.31") -> Hit:
    doc = cid.split("#")[0]
    chunk = Chunk(
        chunk_id=f"v{version}:{cid}", doc_id=doc, version=version, title=doc, section="", text="x"
    )
    return Hit(chunk, score)


class FakeRetriever(Retriever):
    """Real merge logic, canned search results."""

    def __init__(self, results: dict[str, list[Hit]]) -> None:  # pylint: disable=super-init-not-called
        self.aliases: dict[str, str] = {}
        self.results = results
        self.queries: list[str] = []

    def retrieve(self, query, top_k=5, version=None, mode="hybrid_rerank"):  # type: ignore[no-untyped-def]
        self.queries.append(query)
        return self._grouped({"1.31": self.results[query][:top_k]})


def test_strong_search_is_never_rewritten() -> None:
    retriever = FakeRetriever({"q": [hit("a#c1", 0.9)]})
    calls: list[str] = []
    result, query = retrieve_with_rewrite(
        retriever, "q", 5, None, lambda q: calls.append(q) or "x", 0.5
    )
    assert query is None and not calls and retriever.queries == ["q"]
    assert result.chunk_ids() == ["v1.31:a#c1"]


def test_weak_search_is_rewritten_and_merged() -> None:
    retriever = FakeRetriever(
        {
            "vague": [hit("a#c1", 0.2), hit("b#c1", 0.1)],
            "precise": [hit("c#c1", 0.95), hit("a#c1", 0.3)],
        }
    )
    result, query = retrieve_with_rewrite(retriever, "vague", 5, None, lambda q: "precise", 0.5)
    assert query == "precise"
    assert result.chunk_ids() == ["v1.31:c#c1", "v1.31:a#c1", "v1.31:b#c1"]
    assert result.top_score() == 0.95


def test_failed_rewrite_keeps_the_original_result() -> None:
    retriever = FakeRetriever({"vague": [hit("a#c1", 0.2)]})
    result, query = retrieve_with_rewrite(retriever, "vague", 5, None, lambda q: None, 0.5)
    assert query is None and result.chunk_ids() == ["v1.31:a#c1"]


def test_merge_keeps_top_k_per_version() -> None:
    retriever = FakeRetriever({})
    first = retriever._grouped({"1.31": [hit("a#c1", 0.4), hit("b#c1", 0.3)]})  # pylint: disable=protected-access
    second = retriever._grouped({"1.31": [hit("c#c1", 0.9)]})  # pylint: disable=protected-access
    merged: Retrieval = retriever.merge(first, second, top_k=2)
    assert merged.chunk_ids() == ["v1.31:c#c1", "v1.31:a#c1"]
