from __future__ import annotations
import time
from typing import AsyncIterator
from app.core.telemetry import track_event
from app.providers.ollama_provider import OllamaProvider
from app.providers.cloud_provider import CloudProvider


class ProviderRouter:
    def __init__(self) -> None:
        self.ollama = OllamaProvider()
        self.cloud = CloudProvider()

    async def stream_chat(self, messages: list[dict], model: str | None = None, local_first: bool = True) -> AsyncIterator[tuple[str, str]]:
        started = time.perf_counter()
        providers = [self.ollama, self.cloud] if local_first else [self.cloud, self.ollama]
        last_error = None
        for provider in providers:
            try:
                async for token in provider.stream_chat(messages, model=model):
                    yield token, provider.name
                track_event("provider_success", provider=provider.name, latency_ms=round((time.perf_counter()-started)*1000, 2))
                return
            except Exception as exc:
                last_error = str(exc)
                track_event("provider_failure", provider=provider.name, error=str(exc))
        msg = f"No provider could complete the request. Last error: {last_error}"
        for w in msg.split(" "):
            yield w + " ", "none"


router = ProviderRouter()
