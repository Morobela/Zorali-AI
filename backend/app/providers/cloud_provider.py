from __future__ import annotations
import json
from typing import AsyncIterator
import httpx
from app.core.config import settings
from app.providers.base_provider import BaseProvider


class CloudProvider(BaseProvider):
    name = "cloud"

    async def stream_chat(self, messages: list[dict], model: str | None = None) -> AsyncIterator[str]:
        if not settings.cloud_api_key:
            raise RuntimeError("Cloud provider is not configured. Set CLOUD_API_KEY.")
        payload = {
            "model": model or settings.cloud_model,
            "messages": messages,
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {settings.cloud_api_key}",
            "Content-Type": "application/json",
        }
        url = f"{settings.cloud_api_base.rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(timeout=settings.provider_timeout_seconds) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        raw = line[6:].strip()
                        if raw == "[DONE]":
                            break
                        data = json.loads(raw)
                        delta = (data.get("choices") or [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            yield delta

    async def health(self) -> dict:
        return {"provider": self.name, "ok": bool(settings.cloud_api_key), "configured": bool(settings.cloud_api_key)}
