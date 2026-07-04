from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from fastapi import HTTPException, status
from app.core.config import settings

ALGORITHM = "HS256"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(sub: str, role: str = "owner") -> str:
    payload = {
        "sub": sub,
        "role": role,
        "type": "access",
        "exp": _now() + timedelta(minutes=settings.jwt_access_minutes),
        "iat": _now(),
    }
    from app.core.audit import audit, AuditEvent
    audit.record(AuditEvent.AUTH_TOKEN_ISSUED, actor=sub, resource="jwt", role=role)
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_refresh_token(sub: str, role: str = "user") -> str:
    payload = {
        "sub": sub,
        "role": role,
        "type": "refresh",
        "exp": _now() + timedelta(days=settings.jwt_refresh_days),
        "iat": _now(),
    }
    from app.core.audit import audit, AuditEvent
    audit.record(AuditEvent.AUTH_TOKEN_ISSUED, actor=sub, resource="jwt-refresh", role=role)
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate an ACCESS token (refresh tokens are rejected)."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        from app.core.audit import audit, AuditEvent
        audit.record(AuditEvent.AUTH_FAILURE, actor="unknown", resource="jwt", outcome="invalid_token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    # Tokens minted before the type claim existed are access tokens.
    if payload.get("type", "access") != "access":
        from app.core.audit import audit, AuditEvent
        audit.record(AuditEvent.AUTH_FAILURE, actor=payload.get("sub", "unknown"), resource="jwt", outcome="wrong_token_type")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return payload


def decode_refresh_token(token: str) -> dict:
    """Decode and validate a REFRESH token (access tokens are rejected)."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        from app.core.audit import audit, AuditEvent
        audit.record(AuditEvent.AUTH_FAILURE, actor="unknown", resource="jwt-refresh", outcome="invalid_token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    if payload.get("type") != "refresh":
        from app.core.audit import audit, AuditEvent
        audit.record(AuditEvent.AUTH_FAILURE, actor=payload.get("sub", "unknown"), resource="jwt-refresh", outcome="wrong_token_type")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    return payload
