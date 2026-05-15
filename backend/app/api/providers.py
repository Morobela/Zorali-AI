from fastapi import APIRouter
from app.providers.provider_router import router as provider_router
from app.core.config import settings

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("/status")
async def provider_status():
    try:
        ollama = await provider_router.ollama.health()
    except Exception as exc:
        ollama = {"ok": False, "error": f"Ollama unavailable: {exc}"}
    try:
        cloud = await provider_router.cloud.health()
    except Exception as exc:
        cloud = {"ok": False, "error": f"Cloud provider error: {exc}"}
    return {
        "ollama": ollama,
        "cloud": cloud,
        "active_model": settings.ollama_model,
        "last_used_provider": provider_router.last_used_provider,
        "fallback_used": provider_router.fallback_used,
    }
