class GraphAgent:
    async def run(self, task: str):
        return {'agent': 'graph', 'result': f'{task} handled by graph'}
