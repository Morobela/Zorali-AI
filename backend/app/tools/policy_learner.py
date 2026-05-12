class ToolPolicyLearner:
    def __init__(self, tools=None, embedder=None):
        self.tools = tools or []
        self.scores = {t: 0.5 for t in self.tools}
    def choose(self, task: str):
        return sorted(self.scores, key=self.scores.get, reverse=True)
    def update(self, tool: str, success: bool):
        old = self.scores.get(tool, 0.5)
        self.scores[tool] = old * 0.9 + (1.0 if success else 0.0) * 0.1
