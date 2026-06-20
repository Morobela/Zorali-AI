"""
Pytest configuration for backend tests.

Applies a dependency override so all protected HTTP routes accept requests
without a real JWT. The WebSocket handler validates tokens directly in route
code (not via FastAPI Depends), so tests that open a WebSocket must supply
the _WS_TOKEN defined in each test module instead.
"""
from app.main import app
from app.core.rbac import get_current_user


def _test_user() -> dict:
    return {"sub": "test-user", "role": "owner"}


app.dependency_overrides[get_current_user] = _test_user
