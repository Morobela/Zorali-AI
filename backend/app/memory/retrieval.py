"""
Async retrieval entry point with optional dense embeddings.

``HybridRetriever`` is the embedding-capable front door to the hybrid search
engine. When ``rag_embeddings_enabled`` is set and an Ollama embedding model is
reachable, dense cosine similarity is fused in as a third ranker; otherwise it
degrades gracefully to the lexical hybrid + rerank pipeline.
"""
from __future__ import annotations


class HybridRetriever:
    async def retrieve(self, query: str, top_k: int = 5, *, project_id: str = "default"):
        if not query or not query.strip():
            return []
        from app.db.repositories import repo
        from app.memory.hybrid_search import engine, build_chunk_documents
        from app.core.config import settings

        files = repo.list_files(project_id)
        documents = build_chunk_documents(files, contextual=settings.rag_contextual_enabled)
        if not documents:
            return []

        embed_query = None
        doc_embeddings = None
        if settings.rag_embeddings_enabled:
            try:
                from app.memory.embeddings import embed_texts

                doc_embeddings = await embed_texts([d["search_text"] for d in documents])
                q_vecs = await embed_texts([query])
                embed_query = q_vecs[0] if q_vecs else None
            except Exception:
                embed_query = doc_embeddings = None

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
