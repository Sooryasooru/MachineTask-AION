"""Rewrite a vaguely worded question into the documentation's terms, when search is weak.

Questions written from the docs reuse the docs' own words, so search finds them
easily. Real users describe the situation instead ("how long does kubernetes wait
before it force kills my app"), and recall drops (see eval/retrieval_ablation.json).
When the best reranker score is below `REWRITE_BELOW`, a small model rewrites the
question into search terms, the search runs again, and the two results are merged.
Questions that already retrieve well never reach this step, so their path is
unchanged.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from app.config import settings
from rag.retriever import Retrieval, Retriever

RewriteFn = Callable[[str], str | None]

log = logging.getLogger("aion.rewrite")

REWRITE_PROMPT = """Rewrite the user's question as a short search query for the official \
Kubernetes documentation. Use the terms the documentation itself would use: resource \
kinds, field names, flag names and feature names. Keep any release number the user \
gave. Do not answer the question. Return a JSON object: {"query": "..."}"""


def rewrite_query(question: str) -> str | None:
    """Ask the rewrite model for a search query; None if it fails or returns nothing."""
    # pylint: disable=import-outside-toplevel
    from rag.llm import LLMError, call_model

    messages = [
        {"role": "system", "content": REWRITE_PROMPT},
        {"role": "user", "content": question},
    ]
    try:
        reply = json.loads(call_model(settings.rewrite_model, messages, attempts=3))
    except (LLMError, ValueError) as err:
        log.warning("query rewrite failed: %s", err)
        return None
    query = reply.get("query") if isinstance(reply, dict) else None
    return query.strip() if isinstance(query, str) and query.strip() else None


def retrieve_with_rewrite(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    retriever: Retriever,
    question: str,
    top_k: int,
    version: str | None,
    rewrite: RewriteFn | None,
    below: float,
) -> tuple[Retrieval, str | None]:
    """Search; if the best score is under `below`, search a rewritten query too and merge.

    Returns the result and the rewritten query (None when no rewrite was used).
    """
    result = retriever.retrieve(question, top_k=top_k, version=version)
    if rewrite is None or result.top_score() >= below:
        return result, None
    query = rewrite(question)
    if not query:
        return result, None
    second = retriever.retrieve(query, top_k=top_k, version=version)
    return retriever.merge(result, second, top_k), query
