from __future__ import annotations
import json
from typing import AsyncIterator
import httpx
from app.core.config import settings
from app.providers.base_provider import BaseProvider


class OllamaProvider(BaseProvider):
    name = "ollama"

    async def stream_chat(self, messages: list[dict], model: str | None = None) -> AsyncIterator[str]:
        payload = {"model": model or settings.ollama_model, "messages": messages, "stream": True}
        async with httpx.AsyncClient(timeout=settings.provider_timeout_seconds) as client:
            async with client.stream("POST", f"{settings.ollama_host}/api/chat", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("done"):
                        break
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token

    async def health(self) -> dict:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.ollama_host}/api/tags")
            r.raise_for_status()
            models = r.json().get("models", [])
            return {"provider": self.name, "ok": True, "models": [m.get("name") for m in models]}
