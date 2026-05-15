from __future__ import annotations
from typing import AsyncIterator
from app.core.config import settings
from app.providers.base_provider import BaseProvider


class CloudProvider(BaseProvider):
    name = "cloud"

    async def stream_chat(self, messages: list[dict], model: str | None = None) -> AsyncIterator[str]:
        # Placeholder OpenAI-compatible cloud implementation.
        if not settings.cloud_api_key:
            raise RuntimeError("Cloud provider is not configured. Set CLOUD_API_KEY.")
        text = "Cloud fallback provider interface is configured, but concrete vendor SDK is not yet wired."
        for w in text.split(" "):
            yield w + " "

    async def health(self) -> dict:
        return {"provider": self.name, "ok": bool(settings.cloud_api_key), "configured": bool(settings.cloud_api_key)}
