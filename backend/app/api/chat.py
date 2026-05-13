from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.models.llm import stream_llm
from app.reality.project_scanner import status_report
from app.core.config import settings
from app.db.repositories import repo

router = APIRouter()

SYSTEM_PROMPT = """
You are Charlie AI, a local-first J.A.R.V.I.S.-style assistant.
Be useful, direct, and project-aware. Use concise explanations.
When unsure, say what you know and what needs verification.
If citations are provided, reference filenames in your answer.
""".strip()


@router.websocket("/ws/chat/{session_id}")
async def chat_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            mode = data.get("mode", "chat")
            project_id = data.get("project_id", "default")

            if mode == "status":
                project_path = data.get("project_path") or settings.project_root
                await websocket.send_json({"type": "status", "data": status_report(project_path)})
                continue

            message = data.get("message", "").strip()
            if not message:
                await websocket.send_json({"type": "error", "content": "Empty message"})
                continue

            retrieved = repo.search_chunks(project_id, message, limit=3)
            repo.add_chat_message(project_id, session_id, "user", message)
            memory = repo.list_chat_messages(project_id, session_id)
            rag_block = "\n\n".join([f"[{c['filename']}#{c['chunk_id']}] {c['text']}" for c in retrieved])
            prompt_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + ([{"role": "system", "content": f"Project file context:\n{rag_block}"}] if rag_block else []) + [
                {"role": m["role"], "content": m["content"]} for m in memory
            ]
            full = ""
            async for token in stream_llm(prompt_messages):
                full += token
                await websocket.send_json({"type": "token", "content": token})
            citations = [{k: c[k] for k in ("file_id", "filename", "chunk_id")} for c in retrieved]
            repo.add_chat_message(project_id, session_id, "assistant", full, citations=citations)
            await websocket.send_json({"type": "done", "citations": citations})
    except WebSocketDisconnect:
        return
