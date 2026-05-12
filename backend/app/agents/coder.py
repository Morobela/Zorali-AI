class CoderAgent:
    async def run(self, task: str):
        return {'agent': 'coder', 'result': f'{task} handled by coder'}
