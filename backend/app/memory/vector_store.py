"""Memory store with dense semantic recall and a lexical hybrid fallback.

Search order:
1. Dense: when RAG_EMBEDDINGS_ENABLED is on, the query is embedded (Nomic
   ``search_query`` prefix) and ranked by cosine similarity against memory
   embeddings stored at save time — true paraphrase recall.
2. Lexical hybrid: BM25 + TF-IDF fused and reranked with lexical features.
   Used when embeddings are disabled/unavailable or no memory has a vector.
3. Keyword overlap: the repository's simple scorer if the hybrid engine fails.

Memories saved before embeddings were enabled have no vector; they can only
be found lexically until re-saved.
"""
import math

from app.db.repositories import repo


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _strip_embedding(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in ("embedding", "embedding_model")}


class BasicVectorStore:
    """Interface-compatible semantic store: dense first, lexical fallback."""

    async def semantic_search(
        self, project_id: str, user_id: str, query: str, limit: int = 5
    ) -> dict:
        if not query or not query.strip():
            return {"mode": "none", "results": [], "note": "Empty query."}

        # 1. Dense path — only when embeddings are enabled and stored.
        from app.core.config import settings

        if settings.rag_embeddings_enabled:
            try:
                rows = await repo.list_memories(project_id, user_id, include_embedding=True)
                embedded = [r for r in rows if r.get("embedding")]
                if embedded:
                    from app.memory.embeddings import embed_texts

                    vectors = await embed_texts([query], task="query")
                    if vectors:
                        q_vec = vectors[0]
                        scored = [
                            {**_strip_embedding(r), "score": round(_cosine(q_vec, r["embedding"]), 4)}
                            for r in embedded
                        ]
                        scored.sort(key=lambda r: r["score"], reverse=True)
                        return {
                            "mode": "dense",
                            "results": scored[:limit],
                            "note": f"Cosine similarity over {settings.rag_embedding_model} embeddings.",
                        }
            except Exception:
                pass  # degrade to lexical below

        # 2. Lexical hybrid path.
        try:
            from app.memory.hybrid_search import engine

            rows = await repo.list_memories(project_id, user_id)
            if not rows:
                return {"mode": "lexical-hybrid", "results": [], "note": "No memories stored."}
            documents = [{**row, "text": row.get("text", "")} for row in rows]
            results = engine.search(query, documents, top_k=limit)
            return {
                "mode": "lexical-hybrid",
                "results": [{**r.doc, "score": round(r.score, 4)} for r in results],
                "note": "BM25/TF-IDF hybrid; enable RAG_EMBEDDINGS_ENABLED for semantic recall.",
            }
        except Exception:
            results = await repo.search_memories(project_id, user_id, query, limit=limit)
            return {"mode": "keyword-fallback", "results": results, "note": "Keyword overlap fallback."}


vector_store = BasicVectorStore()
