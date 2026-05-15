from app.db.repositories import repo


async def run_file_analysis(message: str, context: dict) -> dict:
    project_id = context.get("project_id", "default")
    hits = repo.search_chunks(project_id, message, limit=5)
    return {
        "agent": "file_analysis",
        "matched_chunks": [{"filename": h["filename"], "chunk_id": h["chunk_id"], "score": h["score"]} for h in hits],
        "summary": "Found relevant uploaded document chunks." if hits else "No matching uploaded document chunks found.",
    }
