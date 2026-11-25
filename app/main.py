"""HTTP API: GET /healthz and POST /ask.

The /ask body is parsed by hand rather than through a Pydantic request model. A
wrong type or broken JSON should still get a schema-valid refusal back, not a 422
or a 500, because the brief treats every response as part of the contract.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.schemas import AskResponse

log = logging.getLogger("aion")
STATE: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Load the index and models once at startup."""
    # pylint: disable=import-outside-toplevel
    from rag.pipeline import load_default_pipeline

    try:
        STATE["pipeline"] = load_default_pipeline()
    except (OSError, ValueError, RuntimeError) as err:  # missing index, bad files
        log.error("pipeline failed to load: %s", err)
        STATE["load_error"] = str(err)
    yield
    STATE.clear()


app = FastAPI(title="AION grounded docs assistant", lifespan=lifespan)


def _refusal(message: str, started: float) -> AskResponse:
    return AskResponse(
        answer=message,
        refused=True,
        citations=[],
        retrieved_chunk_ids=[],
        latency_ms=round((time.perf_counter() - started) * 1000),
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness check."""
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
async def ask(request: Request) -> JSONResponse:
    """Answer a question with citations, or refuse. Always returns the same schema."""
    started = time.perf_counter()
    try:
        body = json.loads(await request.body() or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = None
    if not isinstance(body, dict):
        resp = _refusal("The request body must be a JSON object with a 'question' field.", started)
        return JSONResponse(resp.model_dump())

    pipeline = STATE.get("pipeline")
    if pipeline is None:
        resp = _refusal("The index is not loaded yet. Run `make ingest` and restart.", started)
        return JSONResponse(resp.model_dump())

    try:
        resp = await run_in_threadpool(
            pipeline.ask, body.get("question", ""), body.get("top_k", 5), body.get("version")
        )
    except Exception:  # pylint: disable=broad-exception-caught  # last line of defence
        log.exception("unexpected error while answering")
        resp = _refusal("Something went wrong while answering, so no answer was produced.", started)
    return JSONResponse(resp.model_dump())
