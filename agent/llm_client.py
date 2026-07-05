"""llama.cpp OpenAI-compatible chat client."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib import error, request

from .config import LLMConfig


class LLMClientError(RuntimeError):
    """Raised when the llama.cpp server cannot be reached or returns invalid data."""


@dataclass
class LLMClient:
    config: LLMConfig

    def chat(self, messages: list[dict[str, str]]) -> str:
        url = f"{self.config.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
        except error.URLError as exc:
            raise LLMClientError(
                "Could not connect to llama.cpp server at "
                f"{url}. Start it in server mode and confirm LLM_BASE_URL."
            ) from exc
        try:
            parsed = json.loads(body)
            return parsed["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMClientError(f"Invalid chat completion response from llama.cpp: {body[:500]}") from exc
