"""Loads each local model once per process and picks the device from DEVICE."""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

import torch
from sentence_transformers import CrossEncoder, SentenceTransformer

from app.config import settings


def resolve_device() -> str:
    """DEVICE=auto picks CUDA when present, otherwise CPU."""
    if settings.device != "auto":
        return settings.device
    return "cuda" if torch.cuda.is_available() else "cpu"


@lru_cache(maxsize=1)
def get_embedder() -> SentenceTransformer:
    """bge-small embedder."""
    return SentenceTransformer(settings.embed_model, device=resolve_device())


@lru_cache(maxsize=1)
def get_reranker() -> CrossEncoder:
    """bge-reranker cross-encoder."""
    return CrossEncoder(settings.rerank_model, device=resolve_device())


@lru_cache(maxsize=1)
def get_nli() -> CrossEncoder:
    """NLI cross-encoder used for the support check."""
    return CrossEncoder(settings.nli_model, device=resolve_device())


def nli_scores(pairs: Sequence[tuple[str, str]]) -> list[tuple[float, float, float]]:
    """(contradiction, entailment, neutral) probabilities for (premise, hypothesis) pairs.

    The label order is read from the model config rather than assumed.
    """
    if not pairs:
        return []
    model = get_nli()
    config = getattr(model.model, "config", None)
    id2label = getattr(config, "id2label", None) or {
        0: "contradiction",
        1: "entailment",
        2: "neutral",
    }
    labels = {int(i): str(name).lower() for i, name in dict(id2label).items()}
    logits = torch.tensor(model.predict(list(pairs), convert_to_numpy=True))
    if logits.ndim == 1:
        logits = logits.unsqueeze(0)
    if not torch.allclose(logits.sum(dim=1), torch.ones(len(pairs)), atol=1e-3):
        logits = torch.softmax(logits, dim=1)
    rows = []
    for row in logits.tolist():
        by_name = {labels[i]: p for i, p in enumerate(row)}
        rows.append(
            (
                by_name.get("contradiction", 0.0),
                by_name.get("entailment", 0.0),
                by_name.get("neutral", 0.0),
            )
        )
    return rows
