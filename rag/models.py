"""Loads each local model once per process and picks the device from DEVICE."""

from __future__ import annotations

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
