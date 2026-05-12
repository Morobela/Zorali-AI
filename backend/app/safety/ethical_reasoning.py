from dataclasses import dataclass
@dataclass
class EthicalResult:
    recommendation: str
    reasoning: str
class EthicalConstraintReasoner:
    async def analyse(self, text: str, context=None):
        return EthicalResult('allow', 'No issue detected')
    def format_for_response(self, result):
        return result.reasoning
