class GoalInvariantSystem:
    async def start(self): pass
    async def register_goal(self, goal_id, statement): return {'goal_id':goal_id}
    def log_action(self, action): pass
