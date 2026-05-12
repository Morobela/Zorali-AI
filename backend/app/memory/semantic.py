class SemanticMemory:
    async def add(self, text: str, metadata=None): return {'ok': True}
    async def search(self, query: str, top_k: int = 5): return []
