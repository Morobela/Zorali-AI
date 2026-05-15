from app.db.repositories import repo


class BasicVectorStore:
    """Interface-compatible semantic store.

    Current implementation falls back to keyword overlap search until embeddings are configured.
    """

    def semantic_search(self, project_id: str, user_id: str, query: str, limit: int = 5):
        return repo.search_memories(project_id, user_id, query, limit=limit)


vector_store = BasicVectorStore()
