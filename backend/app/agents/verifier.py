class VerifierAgent:
    async def run(self, task: str):
        return {'agent': 'verifier', 'result': f'{task} handled by verifier'}
