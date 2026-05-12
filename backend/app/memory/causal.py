class CausalMemoryGraph:
    async def record_event(self, event: str, agent: str): return 'event-demo'
    async def counterfactual_plan(self, goal: str, past_failures=None): return ''
    async def extract_causality(self, *args, **kwargs): return None
