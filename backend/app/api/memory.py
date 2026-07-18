from fastapi import APIRouter
from pydantic import BaseModel
from app.core.config import settings
from app.core.rbac import user_or_above
from app.db.repositories import repo
from app.memory.knowledge_graph import knowledge_graph
from app.memory.vector_store import vector_store

router = APIRouter(prefix="/api/memory", tags=["memory"])


class MemoryIn(BaseModel):
    project_id: str
    text: str


@router.post("")
async def save_memory(payload: MemoryIn, _user=user_or_above):
    # Memories are owned by the authenticated caller (JWT sub), never by a
    # client-supplied id — that is what isolates one user's memories from another's.
    embedding = None
    embedding_model = None
    if settings.rag_embeddings_enabled:
        from app.memory.embeddings import embed_texts

        vectors = await embed_texts([payload.text], task="document")
        if vectors:
            embedding = vectors[0]
            embedding_model = settings.rag_embedding_model
    memory = await repo.save_memory(
        payload.project_id, _user["sub"], payload.text,
        embedding=embedding, embedding_model=embedding_model,
    )
    # Graph memory: extract durable facts (subject —relation→ object) so
    # retrieval can follow relationships, not just text similarity.
    triples = await knowledge_graph.extract_and_store(
        payload.text, payload.project_id, _user["sub"], memory["id"]
    )
    return {**memory, "triples": triples, "embedded": embedding is not None}


@router.get("/pending")
async def pending_memories(project_id: str, _user=user_or_above):
    """Auto-extracted candidates awaiting review. Pending rows are never
    searchable and never enter prompts until accepted."""
    return await repo.list_memories(project_id, _user["sub"], status="pending")


@router.post("/{memory_id}/accept")
async def accept_memory(memory_id: str, _user=user_or_above):
    """Promote a pending candidate to a normal memory: embed (when enabled)
    and extract graph triples exactly like an explicitly saved memory."""
    embedding = None
    embedding_model = None
    current = await repo.activate_memory(memory_id, _user["sub"])
    if current is None:
        return {"accepted": False}
    if settings.rag_embeddings_enabled:
        from app.memory.embeddings import embed_texts

        vectors = await embed_texts([current["text"]], task="document")
        if vectors:
            embedding = vectors[0]
            embedding_model = settings.rag_embedding_model
            current = await repo.activate_memory(
                memory_id, _user["sub"], embedding=embedding, embedding_model=embedding_model
            )
    triples = await knowledge_graph.extract_and_store(
        current["text"], current["project_id"], _user["sub"], current["id"]
    )
    return {"accepted": True, **current, "triples": triples, "embedded": embedding is not None}


@router.post("/{memory_id}/reject")
async def reject_memory(memory_id: str, _user=user_or_above):
    """Reject a pending candidate — the row is deleted outright."""
    return {"rejected": await repo.delete_memory(memory_id, _user["sub"])}


@router.get("/search")
async def search_memory(project_id: str, q: str, _user=user_or_above):
    return await repo.search_memories(project_id, _user["sub"], q)


@router.get("/semantic-search")
async def semantic_search_memory(project_id: str, q: str, _user=user_or_above):
    return await vector_store.semantic_search(project_id, _user["sub"], q)


@router.get("/graph")
async def memory_graph(project_id: str, q: str = "", _user=user_or_above):
    """Query the memory knowledge graph.

    With ``q``: triples matching the query entities plus one hop out.
    Without ``q``: every stored triple for the project (graph inspection).
    """
    if q:
        triples = await knowledge_graph.query(q, project_id, _user["sub"])
    else:
        triples = await repo.list_memory_triples(project_id, _user["sub"])
    return {
        "triples": triples,
        "context": "\n".join(f"{t['subject']} —{t['relation']}→ {t['object']}" for t in triples),
    }


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str, _user=user_or_above):
    return {"deleted": await repo.delete_memory(memory_id, _user["sub"])}
