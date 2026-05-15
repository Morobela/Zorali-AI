from fastapi import APIRouter, Query
from pydantic import BaseModel
from app.db.repositories import repo
from app.memory.vector_store import vector_store

router = APIRouter(prefix="/api/memory", tags=["memory"])


class MemoryIn(BaseModel):
    project_id: str
    user_id: str = "local"
    text: str


@router.post("")
def save_memory(payload: MemoryIn):
    return repo.save_memory(payload.project_id, payload.user_id, payload.text)


@router.get("/search")
def search_memory(project_id: str, q: str, user_id: str = Query("local")):
    return repo.search_memories(project_id, user_id, q)


@router.get("/semantic-search")
def semantic_search_memory(project_id: str, q: str, user_id: str = Query("local")):
    return {
        "mode": "basic-semantic-interface",
        "results": vector_store.semantic_search(project_id, user_id, q),
        "note": "Embeddings are not configured; using keyword fallback.",
    }


@router.delete("/{memory_id}")
def delete_memory(memory_id: str, user_id: str = Query("local")):
    return {"deleted": repo.delete_memory(memory_id, user_id)}
