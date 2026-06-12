"""
Role-Based Access Control.
Decorator pattern inspired by TensorFlow's @with_name_scope:
wrap any route handler with role requirements without touching core logic.
"""
from __future__ import annotations
from enum import Enum
from functools import wraps
from typing import Callable
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.auth import decode_token
from app.core.audit import audit, AuditEvent

bearer = HTTPBearer(auto_error=False)


class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    USER = "user"
    READONLY = "readonly"


_ROLE_RANK: dict[Role, int] = {
    Role.READONLY: 0,
    Role.USER: 1,
    Role.ADMIN: 2,
    Role.OWNER: 3,
}


def _rank(role: str) -> int:
    try:
        return _ROLE_RANK[Role(role)]
    except (ValueError, KeyError):
        return -1


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    if not creds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return decode_token(creds.credentials)


def require_role(minimum: Role):
    """
    FastAPI dependency that enforces a minimum role.
    Usage:
        @router.get("/admin-only")
        async def handler(user=Depends(require_role(Role.ADMIN))): ...
    """
    def dependency(user: dict = Depends(get_current_user)) -> dict:
        user_role = user.get("role", "readonly")
        if _rank(user_role) < _rank(minimum):
            audit.record(
                AuditEvent.PERMISSION_DENIED,
                actor=user.get("sub", "unknown"),
                resource="rbac",
                outcome="denied",
                required=minimum.value,
                actual=user_role,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role '{minimum.value}' or higher",
            )
        return user
    return dependency


owner_only = Depends(require_role(Role.OWNER))
admin_or_above = Depends(require_role(Role.ADMIN))
user_or_above = Depends(require_role(Role.USER))
any_authenticated = Depends(get_current_user)
