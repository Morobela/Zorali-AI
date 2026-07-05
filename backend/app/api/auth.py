import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from passlib.context import CryptContext
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token, create_refresh_token, decode_refresh_token
from app.core.config import settings
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/api/auth")

_DEV_ENVS = {"local", "dev", "development", "test"}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class RegisterRequest(LoginRequest):
    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL_RE.match(value) or len(value) > 255:
            raise ValueError("Invalid email address")
        return value

    @field_validator("password")
    @classmethod
    def _valid_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(value.encode()) > 72:  # bcrypt input limit
            raise ValueError("Password must be at most 72 bytes")
        return value


class RefreshRequest(BaseModel):
    refresh_token: str


def _token_response(sub: str, role: str) -> dict:
    return {
        "access_token": create_access_token(sub, role),
        "refresh_token": create_refresh_token(sub, role),
        "token_type": "bearer",
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = (
        await db.execute(select(User.id).where(User.email == payload.email))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")
    # bcrypt is CPU-bound — keep it off the event loop.
    password_hash = await run_in_threadpool(pwd_context.hash, payload.password)
    user = User(id=str(uuid4()), email=payload.email, password_hash=password_hash, role="user")
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")
    return {"id": user.id, "email": user.email, "role": user.role, **_token_response(user.id, user.role)}


@router.post("/login")
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    # Accounts without a password hash (provisioned demo/test users) cannot
    # log in with a password.
    if not user or not user.password_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    valid = await run_in_threadpool(pwd_context.verify, payload.password, user.password_hash)
    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    return _token_response(user.id, user.role)


@router.post("/refresh")
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    claims = decode_refresh_token(payload.refresh_token)
    user = await db.get(User, claims["sub"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown account")
    # Role is re-read from the database so demotions take effect on refresh.
    return _token_response(user.id, user.role)


@router.post("/demo-login")
async def demo_login(db: AsyncSession = Depends(get_db)):
    if settings.app_env not in _DEV_ENVS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    # Provision the demo account row so owner-scoped resources (projects have
    # a FK to users) can be created with this identity.
    if await db.get(User, "demo-owner") is None:
        db.add(User(id="demo-owner", email="demo-owner@zorali.local", role="owner"))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
    return {"access_token": create_access_token("demo-owner", "owner"), "token_type": "bearer"}
