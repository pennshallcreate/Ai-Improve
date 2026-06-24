"""Minimal client for the local Ollama HTTP API — no SDK, no cloud.

Chat streams tokens for the UI; ``generate`` returns a single completion for the
improver. Every call degrades gracefully: if Ollama isn't running or the model is
missing, callers get a clear error/None instead of an exception cascade.
"""
from __future__ import annotations

import json
from typing import Iterator, Optional

import requests


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    # -- health --------------------------------------------------------------
    def is_up(self) -> bool:
        try:
            requests.get(f"{self.base_url}/api/tags", timeout=3).raise_for_status()
            return True
        except requests.RequestException:
            return False

    def available_models(self) -> list[str]:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except requests.RequestException:
            return []

    # -- chat (streaming) ----------------------------------------------------
    def chat_stream(self, messages: list[dict], model: Optional[str] = None) -> Iterator[str]:
        """Yield assistant text chunks. Yields one error string if Ollama is unreachable."""
        payload = {"model": model or self.model, "messages": messages, "stream": True}
        try:
            with requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                stream=True,
                timeout=self.timeout,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    chunk = obj.get("message", {}).get("content", "")
                    if chunk:
                        yield chunk
                    if obj.get("done"):
                        break
        except requests.RequestException as exc:
            yield (
                f"\n\n_[Ollama unavailable: {exc}. Start it with `ollama serve` and "
                f"`ollama pull {model or self.model}`.]_"
            )

    # -- generate (single shot, for the improver) ----------------------------
    def generate(self, prompt: str, model: Optional[str] = None, options: Optional[dict] = None) -> Optional[str]:
        payload = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
            "options": options or {"temperature": 0.2},
        }
        try:
            r = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=self.timeout)
            r.raise_for_status()
            return r.json().get("response", "")
        except requests.RequestException:
            return None
