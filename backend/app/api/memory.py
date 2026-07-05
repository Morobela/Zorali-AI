from fastapi import APIRouter
from pydantic import BaseModel
from app.core.rbac import user_or_above
from app.db.repositories import repo
from app.memory.vector_store import vector_store

router = APIRouter(prefix="/api/memory", tags=["memory"])


class MemoryIn(BaseModel):
    project_id: str
    text: str


@router.post("")
async def save_memory(payload: MemoryIn, _user=user_or_above):
    # Memories are owned by the authenticated caller (JWT sub), never by a
    # client-supplied id — that is what isolates one user's memories from another's.
    return await repo.save_memory(payload.project_id, _user["sub"], payload.text)


@router.get("/search")
async def search_memory(project_id: str, q: str, _user=user_or_above):
    return await repo.search_memories(project_id, _user["sub"], q)


@router.get("/semantic-search")
async def semantic_search_memory(project_id: str, q: str, _user=user_or_above):
    return {
        "mode": "basic-semantic-interface",
        "results": await vector_store.semantic_search(project_id, _user["sub"], q),
        "note": "Embeddings are not configured; using keyword fallback.",
    }


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str, _user=user_or_above):
    return {"deleted": await repo.delete_memory(memory_id, _user["sub"])}
