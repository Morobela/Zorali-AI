class PlannerAgent:
    async def run(self, task: str):
        return {'agent': 'planner', 'result': f'{task} handled by planner'}
