"""Minimal client for any OpenAI-compatible chat endpoint (Groq, Ollama, ...).

Free tiers rate-limit hard, so 429s and 5xx responses are retried with backoff,
honouring Retry-After when the server sends it. Replies can be cached on disk,
keyed by the exact request, which keeps repeated eval runs inside the quota.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

MAX_ATTEMPTS = 8


class LLMError(RuntimeError):
    """The model could not be reached or returned something unusable."""


def _cache_path(payload: dict[str, Any]) -> Path | None:
    if not settings.llm_cache_dir:
        return None
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return Path(settings.llm_cache_dir) / f"{key}.json"


def chat_json(messages: list[dict[str, str]]) -> str:
    """Send a chat request asking for a JSON object; return the raw reply text."""
    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": settings.llm_max_tokens,
        "response_format": {"type": "json_object"},
    }
    if settings.llm_reasoning_effort:
        payload["reasoning_effort"] = settings.llm_reasoning_effort
    cache = _cache_path(payload)
    if cache and cache.exists():
        return cache.read_text(encoding="utf-8")

    headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    delay = 2.0
    last_error = "no attempt made"
    for _ in range(MAX_ATTEMPTS):
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=settings.llm_timeout_s)
        except httpx.HTTPError as err:
            last_error = f"network error: {err}"
            time.sleep(delay)
            delay *= 2
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = f"HTTP {resp.status_code}"
            try:
                wait = float(resp.headers.get("retry-after", ""))
            except ValueError:
                wait = delay
            time.sleep(min(max(wait, 1.0), 60.0))
            delay = min(delay * 2, 60.0)
            continue
        if resp.status_code != 200:
            raise LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            content = str(resp.json()["choices"][0]["message"]["content"])
        except (KeyError, IndexError, ValueError) as err:
            raise LLMError(f"unexpected response shape: {err}") from err
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(content, encoding="utf-8")
        return content
    raise LLMError(f"gave up after {MAX_ATTEMPTS} attempts ({last_error})")
