from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.memory import router as memory_router
from app.api.ollama import router as ollama_router
from app.api.providers import router as providers_router
from app.api.health import router as health_router
from app.api.project import router as project_router
from app.api.auth import router as auth_router
from app.api.tools import router as tools_router
from app.api.files import router as files_router
from app.api.mcp import router as mcp_router
from app.api.ws_ticket import router as ws_ticket_router
from app.api.artifacts import router as artifacts_router
from app.api.skills import router as skills_router
from app.api.inference_stats import router as inference_router
from app.a2a.endpoint import router as a2a_router
from app.core.config import settings
from app.core.rate_limiter import limiter
from app.core.metrics import metrics_endpoint, metrics_middleware
from app.inference.batch_processor import batch_processor
from app.orchestration.task_queue import task_queue
from app.skills.loader import discover_and_load


@asynccontextmanager
async def lifespan(application: FastAPI):
    # Start background services on startup
    await batch_processor.start()
    await task_queue.start()
    if settings.skills_autoload:
        loaded = discover_and_load()
        if loaded:
            print(f"[Zorali] Loaded skills: {loaded}")
    yield
    # Graceful shutdown
    await batch_processor.stop()
    await task_queue.stop()
    from app.core.tickets import close_ticket_store
    await close_ticket_store()


app = FastAPI(title="Zorali", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting middleware (security priority #1)
app.middleware("http")(limiter)

# Prometheus metrics middleware — added last so it is the outermost layer and
# records every request, including rate-limited (429) rejections.
app.middleware("http")(metrics_middleware)


@app.get("/metrics")
async def metrics():
    return metrics_endpoint()

# Original routes — preserved intact
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(memory_router)
app.include_router(ollama_router)
app.include_router(providers_router)
app.include_router(project_router)
app.include_router(tools_router)
app.include_router(files_router)
app.include_router(mcp_router)
app.include_router(ws_ticket_router)
app.include_router(artifacts_router)
app.include_router(a2a_router)

# New enhancement routes
app.include_router(skills_router)
app.include_router(inference_router)


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": "2.0.0",
        "status": "online",
        "message": "Zorali backend is running",
        # Only capabilities wired into a real request path belong here.
        "features": [
            "local-first-execution",
            "streaming-chat",
            "model-driven-tool-use",
            "hybrid-rag-retrieval",
            "deep-research",
            "graph-memory",
            "automatic-memory-review",
            "context-summarization",
            "conversation-titles-and-search",
            "vision-input",
            "sandboxed-code-execution-optin",
            "skills-system",
            "mcp-tools",
            "a2a-endpoint",
            "fault-tolerant-orchestration",
            "async-batch-processing",
            "energy-aware-inference",
            "local-learning-loop",
        ],
    }
