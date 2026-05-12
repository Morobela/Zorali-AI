from collections import defaultdict
from dataclasses import dataclass, field

@dataclass
class ShortTermMemory:
    max_messages: int = 20
    _store: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))

    def get(self, session_id: str) -> list[dict]:
        return self._store[session_id][-self.max_messages:]

    def add(self, session_id: str, role: str, content: str):
        self._store[session_id].append({"role": role, "content": content})
        self._store[session_id] = self._store[session_id][-self.max_messages:]

memory = ShortTermMemory()
