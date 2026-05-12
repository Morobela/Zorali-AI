class EpisodicMemoryStore:
    async def store(self, *args, **kwargs): return {'stored': True}
    async def retrieve_relevant(self, query: str, top_k: int = 5): return []
