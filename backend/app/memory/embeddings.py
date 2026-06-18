"""
Optional dense embeddings via Ollama.

Uses the current Ollama batched embed API (POST /api/embed) with Nomic
task-instruction prefixes so embeddings are generated in the retrieval
mode the model was trained for:

    search_document: <text>   — for document chunks at index time
    search_query: <text>      — for user queries at search time

Without these prefixes the nomic-embed-text family produces suboptimal
similarity scores for asymmetric retrieval (short query vs. long passage).

Texts are sent in bounded batches (EMBED_BATCH_SIZE) rather than one
giant request so very large files do not time out or exhaust Ollama memory.

All failures are logged as warnings and return None so callers degrade
gracefully to lexical hybrid + rerank without crashing.
"""
from __future__ import annotations

import logging
from typing import Sequence

import httpx

from app.core.config import settings

_log = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 32  # chunks per Ollama request


async def embed_texts(
    texts: Sequence[str],
    *,
    task: str = "document",
) -> list[list[float]] | None:
    """Return one embedding vector per text, or None if unavailable.

    Parameters
    ----------
    texts:
        The raw texts to embed (without prefix — this function adds it).
    task:
        ``"document"`` → prepends ``search_document: `` (Nomic retrieval format).
        ``"query"``    → prepends ``search_query: ``    (Nomic query format).
    """
    if not settings.rag_embeddings_enabled or not texts:
        return None

    prefix = "search_query: " if task == "query" else "search_document: "
    prefixed = [f"{prefix}{t}" for t in texts]

    url = f"{settings.ollama_host.rstrip('/')}/api/embed"
    all_vectors: list[list[float]] = []

    try:
        async with httpx.AsyncClient(timeout=settings.provider_timeout_seconds) as client:
            for batch_start in range(0, len(prefixed), EMBED_BATCH_SIZE):
                batch = prefixed[batch_start : batch_start + EMBED_BATCH_SIZE]
                try:
                    resp = await client.post(
                        url,
                        json={"model": settings.rag_embedding_model, "input": batch},
                    )
                    resp.raise_for_status()
                    body = resp.json()
                    batch_vecs = body.get("embeddings")
                    if not batch_vecs or len(batch_vecs) != len(batch):
                        _log.warning(
                            "Ollama embed batch %d–%d returned unexpected shape: "
                            "expected %d vectors, got %r",
                            batch_start,
                            batch_start + len(batch),
                            len(batch),
                            len(batch_vecs) if isinstance(batch_vecs, list) else type(batch_vecs).__name__,
                        )
                        return None
                    all_vectors.extend(batch_vecs)
                except httpx.HTTPStatusError as exc:
                    _log.warning(
                        "Ollama embed batch %d–%d HTTP error %s: %s",
                        batch_start, batch_start + len(batch), exc.response.status_code, exc,
                    )
                    return None
    except Exception as exc:
        _log.warning(
            "Ollama embed unavailable (%s: %s) — falling back to lexical retrieval",
            type(exc).__name__, exc,
        )
        return None

    return all_vectors
