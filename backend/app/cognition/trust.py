from enum import Enum
from dataclasses import dataclass
class SourceType(Enum): HUMAN_UNVERIFIED='human'; MEMORY_RETRIEVAL='memory'; LLM_REASONING='llm'; TOOL_CALL='tool'; DEBATE_CONSENSUS='debate'
@dataclass
class TrustScore: value: float
class TrustPropagator:
    def compose(self, sources):
        if not sources: return TrustScore(0.5)
        return TrustScore(round(sum(v for _,v in sources)/len(sources), 3))
