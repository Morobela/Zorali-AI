class AutonomousRecoveryPlanner:
    async def recover(self, task, failure, state=None):
        return {'succeeded': False, 'reason': 'No recovery attempted in skeleton'}
