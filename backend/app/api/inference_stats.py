"""Inference statistics, energy scoring, and system health API routes."""
from fastapi import APIRouter
from app.inference.energy_scorer import energy_scorer
from app.inference.memory_pool import memory_pool
from app.inference.batch_processor import batch_processor
from app.orchestration.task_queue import task_queue
from app.learning.trace_store import trace_store
from app.learning.local_loop import local_loop
from app.checkpoint.manager import checkpoint_manager
from app.core.rbac import user_or_above, owner_only

router = APIRouter(prefix="/api/inference", tags=["inference"])


@router.get("/energy")
async def energy_stats(_=user_or_above):
    """Current energy and cost scoring statistics."""
    return energy_scorer.stats()


@router.get("/memory")
async def memory_stats(_=user_or_above):
    """Memory pool utilization across concurrent users."""
    return memory_pool.stats()


@router.get("/batch")
async def batch_stats(_=user_or_above):
    """Async batch processor queue depth and active requests."""
    return batch_processor.stats()


@router.get("/queue")
async def queue_stats(_=user_or_above):
    """Task queue status and resource utilization."""
    return task_queue.stats()


@router.get("/learning")
async def learning_stats(_=user_or_above):
    """Local learning loop status and trace collection stats."""
    return {
        "trace_store": trace_store.stats(),
        "routing_hint": local_loop.get_routing_hint(),
        "recent_sessions": local_loop.session_summary(),
    }


@router.post("/learning/run")
async def run_learning_cycle(_=owner_only):
    """Manually trigger a local learning cycle."""
    session = await local_loop.run_cycle()
    return {
        "session_id": session.session_id,
        "status": session.status.value,
        "improvement_pct": round(session.improvement_pct, 2),
        "accepted": session.accepted,
        "changes": session.config_changes,
        "error": session.error,
    }


@router.get("/checkpoints")
async def list_checkpoints(_=owner_only):
    return {"checkpoints": checkpoint_manager.list_checkpoints()}
