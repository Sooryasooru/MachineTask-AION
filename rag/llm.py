"""Minimal client for any OpenAI-compatible chat endpoint (Groq, Ollama, ...).

Free tiers rate-limit hard, so 429s and 5xx responses are retried with backoff,
honouring Retry-After when the server sends it. If a fallback model is set, it takes
over when the main one keeps failing. Replies can be cached on disk,
keyed by the exact request, which keeps repeated eval runs inside the quota.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

MAX_ATTEMPTS = 8
# Counted so a report can say whether its numbers came from live calls or a replay.
STATS = {"cache_hits": 0, "live_calls": 0}
FALLBACK_AFTER = 3  # attempts on the main model before switching, when a fallback is set


log = logging.getLogger("aion.llm")


class LLMError(RuntimeError):
    """The model could not be reached or returned something unusable."""


def _cache_path(payload: dict[str, Any]) -> Path | None:
    if not settings.llm_cache_dir:
        return None
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return Path(settings.llm_cache_dir) / f"{key}.json"


def call_model(model: str, messages: list[dict[str, str]], attempts: int) -> str:
    """One model, with retries on rate limits and server errors."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": settings.llm_max_tokens,
        "response_format": {"type": "json_object"},
    }
    if settings.llm_reasoning_effort:
        payload["reasoning_effort"] = settings.llm_reasoning_effort
    cache = _cache_path(payload)
    if cache and cache.exists():
        STATS["cache_hits"] += 1
        return cache.read_text(encoding="utf-8")

    headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    delay = 2.0
    last_error = "no attempt made"
    for _ in range(attempts):
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
            raise LLMError(f"{model}: HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            content = str(resp.json()["choices"][0]["message"]["content"])
        except (KeyError, IndexError, ValueError) as err:
            raise LLMError(f"{model}: unexpected response shape: {err}") from err
        STATS["live_calls"] += 1
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(content, encoding="utf-8")
        return content
    raise LLMError(f"{model}: gave up after {attempts} attempts ({last_error})")


def chat_json(messages: list[dict[str, str]]) -> str:
    """Ask the main model for a JSON reply; if it fails, try the fallback model once.

    With a fallback configured, the main model gets fewer retries, so a provider
    outage costs seconds rather than minutes before the fallback takes over.
    """
    fallback = settings.llm_fallback_model
    if not fallback or fallback == settings.llm_model:
        return call_model(settings.llm_model, messages, MAX_ATTEMPTS)
    try:
        return call_model(settings.llm_model, messages, FALLBACK_AFTER)
    except LLMError as err:
        log.warning("main model failed (%s); trying fallback %s", err, fallback)
        return call_model(fallback, messages, MAX_ATTEMPTS)
