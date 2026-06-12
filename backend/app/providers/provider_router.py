from __future__ import annotations
import time
from typing import AsyncIterator
from app.core.telemetry import track_event
from app.providers.ollama_provider import OllamaProvider
from app.providers.cloud_provider import CloudProvider
from app.inference.energy_scorer import energy_scorer
from app.core.audit import audit, AuditEvent


class ProviderRouter:
    def __init__(self) -> None:
        self.ollama = OllamaProvider()
        self.cloud = CloudProvider()
        self.last_used_provider = None
        self.fallback_used = False

    async def stream_chat(
        self,
        messages: list[dict],
        model: str | None = None,
        local_first: bool = True,
    ) -> AsyncIterator[tuple[str, str]]:
        # Cost-aware routing: consult energy scorer before choosing order
        # Pattern: OpenJarvis selective cloud offloading
        use_local_first = local_first and energy_scorer.should_prefer_local()

        started = time.perf_counter()
        providers = [self.ollama, self.cloud] if use_local_first else [self.cloud, self.ollama]
        last_error = None
        active_provider = None

        for provider in providers:
            try:
                token_count = 0
                input_tokens = sum(len(m.get("content", "").split()) for m in messages)
                async for token in provider.stream_chat(messages, model=model):
                    self.last_used_provider = provider.name
                    self.fallback_used = provider != providers[0]
                    active_provider = provider.name
                    token_count += 1
                    yield token, provider.name

                latency_ms = (time.perf_counter() - started) * 1000
                score = energy_scorer.score(
                    provider=provider.name,
                    model=model or "default",
                    latency_ms=latency_ms,
                    input_tokens=input_tokens,
                    output_tokens=token_count,
                )
                track_event(
                    "provider_success",
                    provider=provider.name,
                    latency_ms=round(latency_ms, 2),
                    cost_usd=round(score.cost_usd, 6),
                    efficiency=round(score.efficiency_score, 4),
                )
                if self.fallback_used:
                    audit.record(
                        AuditEvent.PROVIDER_SWITCH,
                        resource=provider.name,
                        outcome="fallback",
                        from_provider=providers[0].name,
                    )
                return
            except Exception as exc:
                last_error = str(exc)
                track_event("provider_failure", provider=provider.name, error=str(exc))

        msg = (
            "No provider could complete the request. "
            f"Ollama endpoint: check OLLAMA_HOST/model availability. "
            "Cloud endpoint: ensure CLOUD_API_KEY is set. "
            f"Last error: {last_error}"
        )
        for w in msg.split(" "):
            yield w + " ", "none"


router = ProviderRouter()
