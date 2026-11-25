"""Deterministic scoring rules used by the evaluation."""

from eval.run_eval import answer_text, citation_checks, score

CONFLICT = {"type": "version_conflict", "must_include": ["1.27", "1.31", "two", "three"]}
CHUNKS = {
    "v1.27:d#c1": "may be up to two minor versions older",
    "v1.31:d#c1": "up to three minor versions older",
}


def resp(answer: str, refused: bool = False, cites: list[dict[str, str]] | None = None) -> dict:
    return {"answer": answer, "refused": refused, "citations": cites or []}


def cite(cid: str, quote: str) -> dict[str, str]:
    return {"chunk_id": cid, "doc_id": "d", "version": cid[1:5], "quote": quote}


def test_markers_do_not_count_as_naming_a_version() -> None:
    answer = "The kubelet may lag two or three versions [v1.27:d#c1] [v1.31:d#c1]."
    assert "1.27" not in answer_text(answer)
    both = [cite("v1.27:d#c1", "two minor versions"), cite("v1.31:d#c1", "three minor")]
    assert not score(CONFLICT, resp(answer, cites=both))


def test_conflict_needs_both_versions_named_and_cited() -> None:
    answer = "On 1.27 it is two [v1.27:d#c1]. On 1.31 it is three [v1.31:d#c1]."
    both = [cite("v1.27:d#c1", "two minor versions"), cite("v1.31:d#c1", "three minor")]
    assert score(CONFLICT, resp(answer, cites=both))
    assert not score(CONFLICT, resp(answer, cites=both[:1]))


def test_refusal_scoring() -> None:
    unanswerable = {"type": "unanswerable", "must_include": []}
    assert score(unanswerable, resp("Not covered.", refused=True))
    assert not score(unanswerable, resp("It is 5000 nodes.", refused=False))
    assert not score(CONFLICT, resp("Not covered.", refused=True))


def test_citation_checks() -> None:
    good = resp("A [v1.27:d#c1].", cites=[cite("v1.27:d#c1", "two minor versions")])
    valid, integrity = citation_checks(good, CHUNKS)
    assert valid == [True] and integrity
    bad = resp("A [v1.27:d#c1] [v1.31:d#c9].", cites=[cite("v1.27:d#c1", "four minor versions")])
    valid, integrity = citation_checks(bad, CHUNKS)
    assert valid == [False] and not integrity
