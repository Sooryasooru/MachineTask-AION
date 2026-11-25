"""HTTP contract: health check, and /ask never returns anything but the schema."""

from fastapi.testclient import TestClient

from app.main import STATE, app
from app.schemas import AskResponse

FIELDS = {"answer", "refused", "citations", "retrieved_chunk_ids", "latency_ms"}


class FakePipeline:
    """Echoes the question back as a refusal; enough to test the HTTP layer."""

    def ask(self, question: object, top_k: object = 5, version: object = None) -> AskResponse:
        if question == "boom":
            raise RuntimeError("unexpected")
        return AskResponse(answer=f"got {question!r}", refused=True)


def client() -> TestClient:
    STATE["pipeline"] = FakePipeline()
    return TestClient(app)  # no context manager, so the real models are never loaded


def test_healthz() -> None:
    resp = client().get("/healthz")
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}


def test_ask_returns_schema() -> None:
    resp = client().post("/ask", json={"question": "hi", "top_k": 5})
    assert resp.status_code == 200 and set(resp.json()) == FIELDS


def test_broken_bodies_still_get_the_schema() -> None:
    c = client()
    for body in (b"not json", b"[1, 2]", b""):
        resp = c.post("/ask", content=body, headers={"content-type": "application/json"})
        assert resp.status_code == 200 and set(resp.json()) == FIELDS
        assert resp.json()["refused"] is True


def test_unexpected_error_is_not_a_500() -> None:
    resp = client().post("/ask", json={"question": "boom"})
    assert resp.status_code == 200 and resp.json()["refused"] is True
