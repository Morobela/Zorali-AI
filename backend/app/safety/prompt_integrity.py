import re
from enum import Enum
from dataclasses import dataclass

class TrustLevel(Enum):
    SYSTEM=5; HUMAN_VERIFIED=4; HUMAN_UNVERIFIED=3; TOOL_GENERATED=2; EXTERNAL_WEB=1; UNTRUSTED=0

@dataclass
class ContentEnvelope:
    content: str
    source: str
    trust_level: TrustLevel

class PromptIntegrityEnvelope:
    patterns = [re.compile(r'ignore previous instructions', re.I), re.compile(r'you are now', re.I)]
    def wrap(self, content: str, source: str, trust_level: TrustLevel):
        return ContentEnvelope(content, source, trust_level)
    async def sanitise(self, envelope: ContentEnvelope):
        if any(p.search(envelope.content) for p in self.patterns):
            return ContentEnvelope('[BLOCKED: prompt injection detected]', envelope.source, TrustLevel.UNTRUSTED)
        return envelope
    def build_isolated_prompt(self, parts):
        return '\n\n'.join(f'[{p.trust_level.name}:{p.source}]\n{p.content}' for p in parts)
