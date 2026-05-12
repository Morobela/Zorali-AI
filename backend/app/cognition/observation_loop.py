class ObservationFeedbackLoop:
    async def post_execute_check(self, *args, **kwargs): return {'avg_divergence': 0}
