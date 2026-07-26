import asyncio
import time
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
from app.api.goals import router as goals_router
from app.api.imports import router as imports_router
from app.api.resilience import router as resilience_router
from app.api.selfcheck import router as selfcheck_router
from app.api.webhooks import router as webhooks_router
from app.api.notifications import router as notifications_router
from app.api.skills import router as skills_router
from app.api.inference_stats import router as inference_router
from app.a2a.endpoint import router as a2a_router
from app.core.config import settings
from app.core.rate_limiter import limiter
from app.core.scheduling import seconds_until_next_run as _seconds_until
from app.db.repositories import repo
from app.core.metrics import metrics_endpoint, metrics_middleware
from app.agents.goal_engine import goal_engine
from app.inference.batch_processor import batch_processor
from app.orchestration.task_queue import ExecutionMode, QueuedTask, task_queue
from app.reality.state_engine import reality_engine
from app.skills.loader import discover_and_load


@asynccontextmanager
async def lifespan(application: FastAPI):
    # Start background services on startup
    await batch_processor.start()
    await task_queue.start()
    if settings.reality_scan_enabled:
        # First real producer for the task queue: the continuous reality scan
        # (capability map U3) — snapshot services/git/logs, diff into events,
        # notify on notable changes (U4).
        await task_queue.enqueue(QueuedTask(
            name="reality-scan",
            fn=reality_engine.run_scan,
            mode=ExecutionMode.CONTINUOUS,
            interval_s=settings.reality_scan_interval_seconds,
            priority=7,
        ))
    if settings.goal_engine_enabled and settings.goal_resume_on_boot:
        # Durable goals (capability map U1): continue work a previous process
        # left mid-flight. Detached so a long goal cannot delay startup.
        async def _resume_goals() -> None:
            try:
                resumed = await goal_engine.resume_unfinished_goals()
                if resumed:
                    print(f"[Zorali] Resumed {len(resumed)} interrupted goal(s)")
            except Exception as exc:  # never block startup on a bad goal
                print(f"[Zorali] Goal resume failed: {exc}")

        asyncio.create_task(_resume_goals())

    if settings.self_improvement_enabled:
        # Nightly self-check (capability map U8): run the suite, ruff and the
        # parity checker, then file issues for what they find. Propose-only —
        # it never changes code, and merge authority is never automated.
        async def _nightly_self_check() -> None:
            from app.selfcheck.runner import run_self_check

            await run_self_check(run_tests=settings.self_check_run_tests)
            # Re-arm for the next night.
            await task_queue.enqueue(QueuedTask(
                name="self-check",
                fn=_nightly_self_check,
                mode=ExecutionMode.SCHEDULED,
                run_at=time.time() + _seconds_until(time.time(), settings.self_check_hour_utc),
                priority=8,
            ))

        await task_queue.enqueue(QueuedTask(
            name="self-check",
            fn=_nightly_self_check,
            mode=ExecutionMode.SCHEDULED,
            run_at=time.time() + _seconds_until(time.time(), settings.self_check_hour_utc),
            priority=8,
        ))

    if settings.backup_enabled:
        # Nightly pg_dump with keep-last-N rotation (capability map U9).
        # Only a failed backup notifies — a nightly "backup ok" would train
        # people to ignore the channel that also carries "backup failed".
        async def _nightly_backup() -> None:
            from app.resilience.backup import notify_backup_result, run_backup

            await notify_backup_result(await run_backup())
            await task_queue.enqueue(QueuedTask(
                name="pg-backup",
                fn=_nightly_backup,
                mode=ExecutionMode.SCHEDULED,
                run_at=time.time() + _seconds_until(time.time(), settings.backup_hour_utc),
                priority=8,
            ))

        await task_queue.enqueue(QueuedTask(
            name="pg-backup",
            fn=_nightly_backup,
            mode=ExecutionMode.SCHEDULED,
            run_at=time.time() + _seconds_until(time.time(), settings.backup_hour_utc),
            priority=8,
        ))

    # A repository import runs in a background task; one interrupted by a
    # restart would otherwise claim to be importing forever (capability map
    # U6). Reconcile those rows to failed so the status stays truthful.
    async def _reconcile_imports() -> None:
        try:
            stale = await repo.fail_interrupted_imports()
            if stale:
                print(f"[Zorali] Marked {stale} interrupted import(s) as failed")
        except Exception as exc:
            print(f"[Zorali] Import reconciliation failed: {exc}")

    asyncio.create_task(_reconcile_imports())
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
app.include_router(notifications_router)
app.include_router(goals_router)
app.include_router(imports_router)
app.include_router(webhooks_router)
app.include_router(selfcheck_router)
app.include_router(resilience_router)

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
            "reality-engine",
            "proactive-notifications",
            "durable-goals",
            "bulk-ingestion",
            "repository-import",
            "github-event-inbox",
            "nightly-self-check-propose-only",
            "scheduled-backups-with-rotation",
            "fault-tolerant-orchestration",
            "async-batch-processing",
            "energy-aware-inference",
            "local-learning-loop",
        ],
    }
