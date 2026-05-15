from fastapi import APIRouter
from app.providers.ollama_provider import OllamaProvider

router = APIRouter(prefix="/api/ollama", tags=["ollama"])


@router.get("/health")
async def ollama_health():
    provider = OllamaProvider()
    try:
        return await provider.health()
    except Exception as exc:
        return {
            "provider": "ollama",
            "ok": False,
            "error": f"Ollama unavailable: {exc}. Install Ollama and pull a model, e.g. `ollama pull llama3.2:1b`.",
        }
