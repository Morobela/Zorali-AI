class DebateOrchestrator:
    async def run(self, task: str):
        return {'answer': task, 'consensus_confidence': 0.75}
