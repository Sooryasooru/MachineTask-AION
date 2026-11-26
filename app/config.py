"""Settings, read from environment variables only."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# A local .env is a convenience for development. Real environment variables win.
load_dotenv(override=False)


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    """Everything configurable lives here. No keys or absolute paths in code."""

    port: int = int(_env("PORT", "8080"))

    # Any OpenAI-compatible chat endpoint: Groq, Ollama (/v1), Gemini, OpenRouter...
    llm_base_url: str = _env("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    llm_model: str = _env("LLM_MODEL", "openai/gpt-oss-120b")
    # Used only when the main model keeps failing. Empty disables it (make eval does).
    llm_fallback_model: str = _env("LLM_FALLBACK_MODEL", "openai/gpt-oss-20b")
    llm_api_key: str = _env("LLM_API_KEY", "")
    llm_timeout_s: float = float(_env("LLM_TIMEOUT_S", "60"))
    llm_max_tokens: int = int(_env("LLM_MAX_TOKENS", "2500"))
    # Only sent when set; reasoning models such as gpt-oss accept low / medium / high.
    llm_reasoning_effort: str = _env("LLM_REASONING_EFFORT", "low")
    llm_cache_dir: str = _env("LLM_CACHE_DIR", "")  # empty = no cache

    device: str = _env("DEVICE", "auto")
    embed_model: str = _env("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    rerank_model: str = _env("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
    nli_model: str = _env("NLI_MODEL", "cross-encoder/nli-deberta-v3-small")

    corpus_dir: Path = Path(_env("CORPUS_DIR", "corpus"))
    index_dir: Path = Path(_env("INDEX_DIR", "index"))

    refusal_threshold: float = float(_env("REFUSAL_THRESHOLD", "0.05"))
    nli_entail_threshold: float = float(_env("NLI_ENTAIL_THRESHOLD", "0.5"))
    # Off by default since the ablation in docs/evaluation.md; set to true to re-enable.
    nli_enabled: bool = _env("NLI_ENABLED", "false").lower() in ("1", "true", "yes")
    context_per_version: int = int(_env("CONTEXT_PER_VERSION", "3"))
    context_chars: int = int(_env("CONTEXT_CHARS", "1000"))
    max_question_chars: int = int(_env("MAX_QUESTION_CHARS", "1000"))


settings = Settings()
