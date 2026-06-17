"""
Async retrieval entry point with optional dense embeddings.

``HybridRetriever.retrieve()`` is the canonical retrieval path for async
callers (chat WebSocket, RAG chain, file-analysis agent).

Embedding strategy:
  - Document embeddings are generated at file-upload time and stored in the
    chunk records. This means at query time only the query itself needs to be
    embedded — one request instead of N (one per chunk).
  - If stored embeddings are missing (e.g. files uploaded before the feature
    was enabled), the engine falls back to lexical hybrid + rerank without
    crashing.
  - All embedding failures are logged as warnings rather than raised.
"""
from __future__ import annotations

import logging

# Module-level imports so these bindings are captured once at import time,
# before any test-level module reloads (e.g. importlib.reload(repositories))
# can replace the module-level singletons with temporary instances.
from app.db.repositories import repo
from app.memory.hybrid_search import engine, build_chunk_documents
from app.core.config import settings

_log = logging.getLogger(__name__)


class HybridRetriever:
    async def retrieve(self, query: str, top_k: int = 5, *, project_id: str = "default"):
        if not query or not query.strip():
            return []

        files = repo.list_files(project_id)
        documents = build_chunk_documents(files, contextual=settings.rag_contextual_enabled)
        if not documents:
            return []

        embed_query = None
        doc_embeddings = None

        if settings.rag_embeddings_enabled:
            # Use pre-computed per-chunk embeddings stored at upload time.
            stored = [d.get("embedding") for d in documents]
            if all(v is not None for v in stored):
                doc_embeddings = stored
                try:
                    from app.memory.embeddings import embed_texts  # optional dep, lazy ok
                    q_vecs = await embed_texts([query])
                    embed_query = q_vecs[0] if q_vecs else None
                except Exception as exc:
                    _log.warning("Query embedding failed: %s", exc)
                    embed_query = None
            else:
                # Stored embeddings absent — log once and degrade gracefully.
                _log.debug(
                    "No stored embeddings for project %r; "
                    "dense signal disabled. Upload files with RAG_EMBEDDINGS_ENABLED=true "
                    "to enable semantic retrieval.",
                    project_id,
                )

        results = engine.search(
            query, documents, top_k=top_k,
            embed_query=embed_query, doc_embeddings=doc_embeddings,
        )
        return [
            {
                "file_id": r.doc["file_id"],
                "filename": r.doc["filename"],
                "chunk_id": r.doc["chunk_id"],
                "text": r.doc["text"],
                "score": round(r.score, 4),
            }
            for r in results
        ]


hybrid_retriever = HybridRetriever()
