"""
Optional dense embeddings via Ollama.

This adds a *dense* retrieval signal to the hybrid engine when an Ollama
embedding model is available. It is entirely opt-in (``rag_embeddings_enabled``)
and failure-safe: any network/model problem returns ``None`` so retrieval
silently falls back to the lexical hybrid + rerank pipeline. Nothing here runs
in CI or offline unless explicitly enabled.
"""
from __future__ import annotations

from typing import Sequence

import httpx

from app.core.config import settings


async def embed_texts(texts: Sequence[str]) -> list[list[float]] | None:
    """Return one embedding vector per text, or ``None`` if unavailable."""
    if not settings.rag_embeddings_enabled or not texts:
        return None
    url = f"{settings.ollama_host.rstrip('/')}/api/embeddings"
    vectors: list[list[float]] = []
    try:
        async with httpx.AsyncClient(timeout=settings.provider_timeout_seconds) as client:
            for text in texts:
                resp = await client.post(
                    url,
                    json={"model": settings.rag_embedding_model, "prompt": text},
                )
                resp.raise_for_status()
                emb = resp.json().get("embedding")
                if not emb:
                    return None
                vectors.append(emb)
    except Exception:
        return None
    return vectors
