from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from fastapi import HTTPException, status
from app.core.config import settings

ALGORITHM = "HS256"


def create_access_token(sub: str, role: str = "owner") -> str:
    payload = {
        "sub": sub,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=60),
        "iat": datetime.now(timezone.utc),
    }
    from app.core.audit import audit, AuditEvent
    audit.record(AuditEvent.AUTH_TOKEN_ISSUED, actor=sub, resource="jwt", role=role)
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        from app.core.audit import audit, AuditEvent
        audit.record(AuditEvent.AUTH_FAILURE, actor="unknown", resource="jwt", outcome="invalid_token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
