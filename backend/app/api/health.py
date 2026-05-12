from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(prefix="/api")

@router.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}
