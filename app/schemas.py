"""Request and response shapes for the API. These match the brief exactly."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """Body of POST /ask.

    Fields are deliberately loose. Bad input should come back as a schema-valid
    refusal, not a 422 from the framework.
    """

    question: str = ""
    top_k: int = 5
    version: Literal["1.27", "1.31"] | None = None


class Citation(BaseModel):
    """One cited chunk. `quote` must be an exact substring of that chunk."""

    doc_id: str
    chunk_id: str
    version: str
    quote: str


class AskResponse(BaseModel):
    """Body returned by POST /ask, for answers, refusals and errors alike."""

    answer: str
    refused: bool
    citations: list[Citation] = Field(default_factory=list)
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    latency_ms: int = 0
