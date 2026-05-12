import pytest
from app.safety.action_classifier import ActionSafetyGate

@pytest.mark.asyncio
async def test_delete_blocked_for_user():
    gate = ActionSafetyGate()
    result = await gate.authorize('delete_file', {'path':'x'}, 'user')
    assert result['authorized'] is False
