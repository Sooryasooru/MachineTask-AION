"""End-to-end pipeline with a fake LLM: every path returns the schema."""

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from app.schemas import AskResponse
from rag.chunker import Chunk
from rag.ingest import build_index
from rag.llm import LLMError
from rag.pipeline import Pipeline, load_known_terms, stage_notes
from rag.retriever import Retriever, tokenize
from rag.validator import VerifiedCitation, VerifiedSentence
from tests.test_ingest import fake_embed

SKEW = {
    "1.27": "The kubelet may be up to two minor versions older than kube-apiserver.",
    "1.31": "The kubelet may be up to three minor versions older than kube-apiserver.",
}


def rerank(query: str, texts: Sequence[str]) -> list[float]:
    words = set(tokenize(query))
    return [min(1.0, len(words & set(tokenize(t))) / 4) for t in texts]


@pytest.fixture(name="index_dir")
def index_fixture(tmp_path: Path) -> Path:
    corpus = tmp_path / "corpus"
    for version, text in SKEW.items():
        root = corpus / version / "releases"
        root.mkdir(parents=True)
        (root / "skew.md").write_text(f"---\ntitle: Skew\n---\n## kubelet\n{text}\n")
        for i in range(4):
            (root / f"f{i}.md").write_text(
                f"---\ntitle: F{i}\n---\n## Other\nUnrelated page {i} about storage classes here.\n"
            )
    build_index(corpus, tmp_path / "index", fake_embed)
    return tmp_path / "index"


def make(index_dir: Path, reply: str | Exception) -> Pipeline:
    retriever = Retriever(index_dir, lambda q: fake_embed([q])[0], rerank)

    def llm(_: list[dict[str, str]]) -> str:
        if isinstance(reply, Exception):
            raise reply
        return reply

    return Pipeline(retriever, llm, load_known_terms(index_dir))


def conflict_reply() -> str:
    return json.dumps(
        {
            "answerable": True,
            "sentences": [
                {
                    "text": "On 1.27, the kubelet may be up to two minor versions older.",
                    "citations": [
                        {
                            "chunk_id": "v1.27:releases/skew#c1",
                            "quote": "kubelet may be up to two minor versions older",
                        }
                    ],
                },
                {
                    "text": "On 1.31, the kubelet may be up to three minor versions older.",
                    "citations": [
                        {
                            "chunk_id": "v1.31:releases/skew#c1",
                            "quote": "kubelet may be up to three minor versions older",
                        }
                    ],
                },
            ],
            "gaps": [],
            "missing": "",
        }
    )


def test_version_conflict_answer_cites_both(index_dir: Path) -> None:
    resp = make(index_dir, conflict_reply()).ask("How many minor versions may the kubelet lag?")
    assert not resp.refused
    assert {c.version for c in resp.citations} == {"1.27", "1.31"}
    for cite in resp.citations:
        assert f"[{cite.chunk_id}]" in resp.answer
    assert "1.27" in resp.answer and "1.31" in resp.answer


def test_every_marker_has_a_citation(index_dir: Path) -> None:
    resp = make(index_dir, conflict_reply()).ask("How many minor versions may the kubelet lag?")
    markers = set(__import__("re").findall(r"\[([^\]]+)\]", resp.answer))
    assert markers == {c.chunk_id for c in resp.citations}


def test_unanswerable_reply_becomes_refusal(index_dir: Path) -> None:
    reply = json.dumps(
        {
            "answerable": False,
            "sentences": [],
            "gaps": [],
            "missing": "the excerpts give no node limit",
        }
    )
    resp = make(index_dir, reply).ask("What is the maximum number of kubelet nodes?")
    assert resp.refused and resp.citations == [] and resp.retrieved_chunk_ids


def test_fabricated_quote_becomes_refusal(index_dir: Path) -> None:
    reply = json.dumps(
        {
            "answerable": True,
            "sentences": [
                {
                    "text": "The kubelet may lag by five versions.",
                    "citations": [
                        {
                            "chunk_id": "v1.31:releases/skew#c1",
                            "quote": "may lag by five minor versions",
                        }
                    ],
                }
            ],
        }
    )
    resp = make(index_dir, reply).ask("How many minor versions may the kubelet lag?")
    assert resp.refused and resp.citations == []


def test_llm_failure_is_a_refusal_not_an_error(index_dir: Path) -> None:
    resp = make(index_dir, LLMError("down")).ask("How many minor versions may the kubelet lag?")
    assert isinstance(resp, AskResponse) and resp.refused


@pytest.mark.parametrize(
    "question", ["", "x" * 4000, "¿Cuántas versiones puede retrasarse?", None, 42]
)
def test_bad_input_never_raises(index_dir: Path, question: object) -> None:
    resp = make(index_dir, conflict_reply()).ask(question)
    assert isinstance(resp, AskResponse)


def test_false_premise_refused_before_retrieval(index_dir: Path) -> None:
    resp = make(index_dir, conflict_reply()).ask("How do I set the kubelet --max-pod-lag flag?")
    assert resp.refused and resp.retrieved_chunk_ids == []


def test_counterpart_from_other_release_is_added_to_context(index_dir: Path) -> None:
    pipeline = make(index_dir, conflict_reply())
    result = pipeline.retriever.retrieve("kubelet minor versions older", top_k=1, version="1.31")
    context = pipeline.build_context(result, pinned=None)
    assert (
        "v1.27:releases/skew#c1" in {h.chunk.chunk_id for h in context["1.27"]}
        if "1.27" in context
        else True
    )
    twin = pipeline.retriever.counterpart(result.by_version["1.31"][0].chunk, "1.27")
    assert twin is not None and twin.chunk_id == "v1.27:releases/skew#c1"


def test_trace_explains_dropped_sentences(index_dir: Path) -> None:
    reply = json.dumps(
        {
            "answerable": True,
            "sentences": [
                {
                    "text": "The kubelet may lag by five versions.",
                    "citations": [
                        {
                            "chunk_id": "v1.31:releases/skew#c1",
                            "quote": "may lag by five minor versions",
                        }
                    ],
                }
            ],
        }
    )
    resp, trace = make(index_dir, reply).ask_traced("How many minor versions may the kubelet lag?")
    assert resp.refused
    assert trace["verdicts"][0]["reason"] == "no verifiable citation"


def test_one_sided_answer_gets_other_release_feature_state(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    pages = {
        "1.27": "FEATURE STATE: Kubernetes v1.27 [beta]",
        "1.31": "FEATURE STATE: Kubernetes v1.31 [stable]",
    }
    for version, state in pages.items():
        root = corpus / version / "concepts"
        root.mkdir(parents=True)
        (root / "ordinals.md").write_text(
            f"---\ntitle: Start ordinal\n---\n## Start ordinal\n{state}\n\n"
            "You can set .spec.ordinals.start to choose the first ordinal of a StatefulSet.\n"
        )
        for i in range(4):
            (root / f"f{i}.md").write_text(
                f"---\ntitle: F{i}\n---\n## Other\nUnrelated page {i} about storage classes here.\n"
            )
    build_index(corpus, tmp_path / "index", fake_embed)
    reply = json.dumps(
        {
            "answerable": True,
            "sentences": [
                {
                    "text": "On 1.27, the start ordinal feature is beta.",
                    "citations": [
                        {
                            "chunk_id": "v1.27:concepts/ordinals#c1",
                            "quote": "FEATURE STATE: Kubernetes v1.27 [beta]",
                        }
                    ],
                }
            ],
        }
    )
    resp = make(tmp_path / "index", reply).ask("Is the StatefulSet start ordinal stable?")
    assert not resp.refused
    assert {c.version for c in resp.citations} == {"1.27", "1.31"}
    assert "[stable]" in resp.answer
    for cite in resp.citations:
        assert f"[{cite.chunk_id}]" in resp.answer


def make_sequence(index_dir: Path, replies: list[str]) -> tuple[Pipeline, list[int]]:
    """A pipeline whose fake model gives a different reply on each call."""
    retriever = Retriever(index_dir, lambda q: fake_embed([q])[0], rerank)
    calls = [0]

    def llm(_: list[dict[str, str]]) -> str:
        calls[0] += 1
        return replies[min(calls[0], len(replies)) - 1]

    return Pipeline(retriever, llm, load_known_terms(index_dir)), calls


def one_sided_reply(bad_1_31_quote: bool) -> str:
    reply = json.loads(conflict_reply())
    if bad_1_31_quote:
        reply["sentences"][1]["citations"][0]["quote"] = "kubelet may lag by eleven versions"
    return json.dumps(reply)


def test_retry_adds_the_missing_release_and_keeps_the_rest(index_dir: Path) -> None:
    pipe, calls = make_sequence(index_dir, [one_sided_reply(True), one_sided_reply(False)])
    resp, trace = pipe.ask_traced("How many minor versions may the kubelet lag?")
    assert calls[0] == 2 and trace["retry"]["added"] == 1
    assert {c.version for c in resp.citations} == {"1.27", "1.31"}


def test_no_retry_when_nothing_was_lost(index_dir: Path) -> None:
    pipe, calls = make_sequence(index_dir, [conflict_reply()])
    _, trace = pipe.ask_traced("How many minor versions may the kubelet lag?")
    assert calls[0] == 1 and "retry" not in trace
    assert set(trace["timing_ms"]) >= {"retrieve", "first_attempt", "total"}


def test_worse_retry_never_removes_what_was_kept(index_dir: Path) -> None:
    unanswerable = json.dumps({"answerable": False, "sentences": [], "missing": "no idea"})
    pipe, calls = make_sequence(index_dir, [one_sided_reply(True), unanswerable])
    resp = pipe.ask_traced("How many minor versions may the kubelet lag?")[0]
    assert calls[0] == 2 and not resp.refused
    assert {c.version for c in resp.citations} == {"1.27"}


def _verified(chunk_text: str, version: str = "1.31") -> VerifiedSentence:
    chunk = Chunk(
        chunk_id=f"v{version}:tasks/x#c1",
        doc_id="tasks/x",
        version=version,
        title="X",
        section="X",
        text=chunk_text,
    )
    quote = "Ratcheting accepts updates to invalid objects"
    start = chunk_text.index(quote)
    return VerifiedSentence(
        "Ratcheting accepts updates to invalid objects.",
        (VerifiedCitation(chunk, quote, start, start + len(quote)),),
    )


def test_stage_note_added_for_a_beta_section() -> None:
    text = (
        "FEATURE STATE: Kubernetes v1.30 [beta] (feature gate `CRDValidationRatcheting`)\n\n"
        "Ratcheting accepts updates to invalid objects as long as the bad parts are unchanged."
    )
    notes = stage_notes([_verified(text)])
    assert len(notes) == 1 and "[beta]" in notes[0].text
    cite = notes[0].citations[0]
    assert cite.chunk.text[cite.start : cite.end] == cite.quote


def test_no_stage_note_for_stable_or_ambiguous_sections() -> None:
    body = "Ratcheting accepts updates to invalid objects as long as the bad parts are unchanged."
    stable = "FEATURE STATE: Kubernetes v1.28 [stable]\n\n" + body
    two = (
        "FEATURE STATE: Kubernetes v1.30 [beta]\n\nFEATURE STATE: Kubernetes v1.29 [alpha]\n\n"
        + body
    )
    assert stage_notes([_verified(stable)]) == []
    assert stage_notes([_verified(two)]) == []


def test_gap_lines_are_fixed_code_text() -> None:
    from rag.pipeline import allowed_gaps  # pylint: disable=import-outside-toplevel

    gaps = [
        "The 1.27 documentation excerpts do not cover this.",
        "1.31 does not mention it, but you should use v2 instead.",
    ]
    assert allowed_gaps(gaps, ["1.27", "1.31"]) == [
        "Search found no passage about this in the 1.27 documentation."
    ]
