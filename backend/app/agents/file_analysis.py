from app.memory.retrieval import hybrid_retriever


async def run_file_analysis(message: str, context: dict) -> dict:
    project_id = context.get("project_id", "default")
    hits = await hybrid_retriever.retrieve(message, top_k=5, project_id=project_id)
    return {
        "agent": "file_analysis",
        "matched_chunks": [{"filename": h["filename"], "chunk_id": h["chunk_id"], "score": h["score"]} for h in hits],
        "summary": "Found relevant uploaded document chunks." if hits else "No matching uploaded document chunks found.",
    }
