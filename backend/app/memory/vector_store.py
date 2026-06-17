"""
Semantic store for user/project memories.

Routes memory search through the hybrid retrieval engine (BM25 + TF-IDF fused
and reranked) instead of raw keyword overlap, so paraphrased recall works. Falls
back to the repository's keyword search if anything goes wrong.
"""
from app.db.repositories import repo


class BasicVectorStore:
    """Interface-compatible semantic store backed by the hybrid search engine."""

    def semantic_search(self, project_id: str, user_id: str, query: str, limit: int = 5):
        if not query or not query.strip():
            return []
        try:
            from app.memory.hybrid_search import engine

            rows = repo.list_memories(project_id, user_id)
            if not rows:
                return []
            documents = [{**row, "text": row.get("text", "")} for row in rows]
            results = engine.search(query, documents, top_k=limit)
            return [{**r.doc, "score": round(r.score, 4)} for r in results]
        except Exception:
            return repo.search_memories(project_id, user_id, query, limit=limit)


vector_store = BasicVectorStore()
