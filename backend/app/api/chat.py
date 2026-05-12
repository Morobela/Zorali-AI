from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.memory.short_term import memory
from app.models.llm import stream_llm
from app.reality.project_scanner import status_report
from app.core.config import settings

router = APIRouter()

SYSTEM_PROMPT = """
You are Charlie AI, a local-first J.A.R.V.I.S.-style assistant.
Be useful, direct, and project-aware. Use concise explanations.
When unsure, say what you know and what needs verification.
""".strip()

@router.websocket("/ws/chat/{session_id}")
async def chat_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            mode = data.get("mode", "chat")

            if mode == "status":
                project_path = data.get("project_path") or settings.project_root
                await websocket.send_json({"type": "status", "data": status_report(project_path)})
                continue

            if mode == "task":
                task = data.get("message", "")
                report = status_report(settings.project_root)
                await websocket.send_json({
                    "type": "task_result",
                    "data": {
                        "status": "complete",
                        "result": f"Phase 1 task mode received: {task}",
                        "project_status": report["status_report"],
                        "steps_executed": 1,
                    },
                })
                continue

            message = data.get("message", "").strip()
            if not message:
                await websocket.send_json({"type": "error", "content": "Empty message"})
                continue

            memory.add(session_id, "user", message)
            messages = [{"role": "system", "content": SYSTEM_PROMPT}] + memory.get(session_id)
            full = ""
            async for token in stream_llm(messages):
                full += token
                await websocket.send_json({"type": "token", "content": token})
            memory.add(session_id, "assistant", full)
            await websocket.send_json({
                "type": "done",
                "trust_score": 0.82,
                "reasoning_depth": "standard",
                "tools_used": [],
                "recovery_used": False,
            })
    except WebSocketDisconnect:
        return
