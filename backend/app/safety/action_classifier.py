from enum import Enum
from dataclasses import dataclass

class SafetyClass(str, Enum):
    LOW='low'; MEDIUM='medium'; HIGH='high'; CRITICAL='critical'

@dataclass
class ActionSpec:
    name: str
    safety_class: SafetyClass
    requires_approval: bool

ACTION_REGISTRY = {
    'read_file': ActionSpec('read_file', SafetyClass.LOW, False),
    'write_file': ActionSpec('write_file', SafetyClass.HIGH, True),
    'delete_file': ActionSpec('delete_file', SafetyClass.CRITICAL, True),
    'run_python': ActionSpec('run_python', SafetyClass.HIGH, True),
}

class ActionSafetyGate:
    async def authorize(self, action_name: str, action_args: dict, user_role: str = 'user') -> dict:
        spec = ACTION_REGISTRY.get(action_name, ActionSpec(action_name, SafetyClass.MEDIUM, True))
        if spec.requires_approval and user_role not in {'admin','owner'}:
            return {'authorized': False, 'reason': f'{action_name} requires approval/admin role'}
        return {'authorized': True, 'spec': spec}
