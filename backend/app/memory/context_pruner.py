from dataclasses import dataclass
@dataclass
class ContextItem:
    id: str; content: str; role: str; tokens: int = 0; salience: float = 0.5; age_turns: int = 0; referenced_count: int = 0
class DynamicContextPruner:
    async def prune(self, items, current_task: str): return items[-20:]
