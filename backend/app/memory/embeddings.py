"""
Optional dense embeddings via Ollama.

Uses the current Ollama batch embed API (POST /api/embed with an ``input``
array) rather than the deprecated /api/embeddings single-text endpoint.
One HTTP request embeds all texts in a batch, which is substantially more
efficient than the per-text loop the old endpoint required.

Failures are logged as warnings and return ``None`` so callers degrade
gracefully to lexical hybrid + rerank without crashing.
"""
from __future__ import annotations

import logging
from typing import Sequence

import httpx

from app.core.config import settings

_log = logging.getLogger(__name__)


async def embed_texts(texts: Sequence[str]) -> list[list[float]] | None:
    """Return one embedding vector per text, or ``None`` if unavailable.

    Uses the batched /api/embed endpoint introduced in Ollama 0.1.x:
        POST /api/embed  {"model": "...", "input": ["text1", "text2", ...]}
        → {"embeddings": [[...], [...]]}
    """
    if not settings.rag_embeddings_enabled or not texts:
        return None
    url = f"{settings.ollama_host.rstrip('/')}/api/embed"
    try:
        async with httpx.AsyncClient(timeout=settings.provider_timeout_seconds) as client:
            resp = await client.post(
                url,
                json={"model": settings.rag_embedding_model, "input": list(texts)},
            )
            resp.raise_for_status()
            body = resp.json()
            vectors = body.get("embeddings")
            if not vectors or len(vectors) != len(texts):
                _log.warning(
                    "Ollama embed returned unexpected shape: expected %d vectors, got %r",
                    len(texts),
                    len(vectors) if isinstance(vectors, list) else type(vectors).__name__,
                )
                return None
            return vectors
    except httpx.HTTPStatusError as exc:
        _log.warning("Ollama embed HTTP error %s: %s", exc.response.status_code, exc)
        return None
    except Exception as exc:
        _log.warning("Ollama embed unavailable (%s: %s) — falling back to lexical retrieval",
                     type(exc).__name__, exc)
        return None
