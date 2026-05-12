class KnowledgeGraph:
    async def graph_context_for_query(self, query: str): return ''
    async def extract_and_store(self, text: str, session_id: str): return {'stored': True}
