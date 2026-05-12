class ResearcherAgent:
    async def run(self, task: str):
        return {'agent': 'researcher', 'result': f'{task} handled by researcher'}
