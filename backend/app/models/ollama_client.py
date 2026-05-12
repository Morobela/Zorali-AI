import json
import httpx
from typing import AsyncIterator
from app.core.config import settings


async def stream_chat(messages: list[dict], model: str | None = None) -> AsyncIterator[str]:
    """Stream tokens from Ollama. Falls back gracefully if Ollama is not ready."""
    payload = {
        "model": model or settings.ollama_model,
        "messages": messages,
        "stream": True,
    }
    url = f"{settings.ollama_host}/api/chat"
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, json=payload) as response:
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
    except Exception as exc:
        fallback = (
            "Charlie AI backend is running, but Ollama is not ready yet. "
            "Run: docker compose exec ollama ollama pull llama3.1. "
            f"Details: {exc}"
        )
        for word in fallback.split(" "):
            yield word + " "
