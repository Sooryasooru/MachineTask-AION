"""The response schema is part of the contract, so it gets tested first."""

from app.schemas import AskRequest, AskResponse, Citation


def test_refusal_has_every_field() -> None:
    resp = AskResponse(answer="Not covered.", refused=True)
    data = resp.model_dump()
    assert set(data) == {"answer", "refused", "citations", "retrieved_chunk_ids", "latency_ms"}
    assert data["citations"] == []


def test_empty_question_is_accepted() -> None:
    # An empty question must reach our own guard, not fail validation.
    assert AskRequest(question="").question == ""


def test_citation_round_trip() -> None:
    cite = Citation(
        doc_id="releases/version-skew-policy",
        chunk_id="v1.31:releases/version-skew-policy#c3",
        version="1.31",
        quote="kubelet may be up to three minor versions older",
    )
    assert AskResponse(answer="x", refused=False, citations=[cite]).citations[0] == cite
