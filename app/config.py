"""Settings, read from environment variables only."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    """Everything configurable lives here. No keys or absolute paths in code."""

    port: int = int(_env("PORT", "8080"))
    llm_provider: str = _env("LLM_PROVIDER", "groq")
    groq_api_key: str = _env("GROQ_API_KEY", "")
    groq_model: str = _env("GROQ_MODEL", "llama-3.3-70b-versatile")
    ollama_url: str = _env("OLLAMA_URL", "http://localhost:11434")
    ollama_model: str = _env("OLLAMA_MODEL", "qwen2.5:3b")
    device: str = _env("DEVICE", "auto")
    embed_model: str = _env("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    rerank_model: str = _env("RERANK_MODEL", "BAAI/bge-reranker-base")
    nli_model: str = _env("NLI_MODEL", "cross-encoder/nli-deberta-v3-small")
    corpus_dir: Path = Path(_env("CORPUS_DIR", "corpus"))
    index_dir: Path = Path(_env("INDEX_DIR", "index"))
    refusal_threshold: float = float(_env("REFUSAL_THRESHOLD", "0.0"))


settings = Settings()
