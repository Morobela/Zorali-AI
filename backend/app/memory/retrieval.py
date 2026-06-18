"""
Async retrieval entry point with optional dense embeddings.

``HybridRetriever.retrieve()`` is the canonical retrieval path for every async
caller: chat WebSocket, sequential RAG chain, /api/files/search, and the
file-analysis agent.

Dense embedding strategy:
  - Embeddings are generated at file-upload time (task="document") and stored
    per-chunk in the file record. Only the query needs to be embedded at search
    time (task="query"), using the same Nomic task-instruction prefix.
  - Dense retrieval is *partial*: chunks without stored embeddings (e.g. files
    uploaded before the feature was enabled) are still retrieved via the lexical
    pipeline and participate in RRF fusion. Only the subset with stored embeddings
    contributes a dense ranking. This avoids the "one old file disables everything"
    failure mode.
  - Stored embeddings that were generated with a different model than the current
    ``RAG_EMBEDDING_MODEL`` are silently skipped to prevent cross-space comparisons.
  - All failures are logged as warnings; the engine degrades gracefully to
    lexical hybrid + reranking.
"""
from __future__ import annotations

import logging

# Module-level imports so these bindings are captured once at import time,
# before any test-level module reloads (e.g. importlib.reload(repositories))
# can replace the module-level singletons with temporary instances.
from app.db.repositories import repo
from app.memory.hybrid_search import engine, build_chunk_documents, cosine_rank
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

        dense_ranking: list[tuple[int, float]] | None = None

        if settings.rag_embeddings_enabled:
            current_model = settings.rag_embedding_model
            # Collect (original_index, vector) for chunks with matching-model embeddings.
            indexed: list[tuple[int, list[float]]] = [
                (i, d["embedding"])
                for i, d in enumerate(documents)
                if d.get("embedding") is not None
                and d.get("embedding_model") == current_model
            ]
            if indexed:
                try:
                    from app.memory.embeddings import embed_texts
                    q_vecs = await embed_texts([query], task="query")
                    if q_vecs:
                        orig_indices, sub_vecs = zip(*indexed)
                        sub_rankings = cosine_rank(q_vecs[0], list(sub_vecs))
                        # Remap sub-corpus indices back to original document indices.
                        dense_ranking = [(orig_indices[si], score) for si, score in sub_rankings]
                except Exception as exc:
                    _log.warning("Dense query embedding failed: %s", exc)
            elif documents:
                _log.debug(
                    "No stored embeddings (model=%r) for project %r; "
                    "dense signal skipped. Re-upload files with RAG_EMBEDDINGS_ENABLED=true "
                    "to enable semantic retrieval.",
                    current_model, project_id,
                )

        results = engine.search(
            query, documents, top_k=top_k,
            extra_rankings=[dense_ranking] if dense_ranking else None,
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
