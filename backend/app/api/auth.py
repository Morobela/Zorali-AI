from fastapi import APIRouter, HTTPException, status
from app.core.auth import create_access_token
from app.core.config import settings

router = APIRouter(prefix="/api/auth")

_DEV_ENVS = {"local", "dev", "development", "test"}


@router.post("/demo-login")
async def demo_login():
    if settings.app_env not in _DEV_ENVS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return {"access_token": create_access_token("demo-owner", "owner"), "token_type": "bearer"}
