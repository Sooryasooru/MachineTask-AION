"""LLM client: retries, fallback model, and errors that never leak as crashes."""

from dataclasses import replace

import httpx
import pytest

import rag.llm as llm


class FakeResponse:
    def __init__(self, status: int, content: str = "{}") -> None:
        self.status_code = status
        self.text = "error"
        self.headers: dict[str, str] = {"retry-after": "0"}
        self._content = content

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


def use_settings(monkeypatch: pytest.MonkeyPatch, **changes: object) -> None:
    monkeypatch.setattr(llm, "settings", replace(llm.settings, llm_cache_dir="", **changes))
    monkeypatch.setattr(llm.time, "sleep", lambda _: None)


def test_fallback_takes_over_when_main_model_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    use_settings(monkeypatch, llm_model="main", llm_fallback_model="backup")
    seen: list[str] = []

    def post(url: str, json: dict, headers: dict, timeout: float) -> FakeResponse:
        seen.append(json["model"])
        return FakeResponse(503) if json["model"] == "main" else FakeResponse(200, '{"ok": 1}')

    monkeypatch.setattr(httpx, "post", post)
    assert llm.chat_json([{"role": "user", "content": "hi"}]) == '{"ok": 1}'
    assert seen.count("main") == llm.FALLBACK_AFTER and seen[-1] == "backup"


def test_no_fallback_raises_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    use_settings(monkeypatch, llm_model="main", llm_fallback_model="")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(401))
    with pytest.raises(llm.LLMError):
        llm.chat_json([{"role": "user", "content": "hi"}])
