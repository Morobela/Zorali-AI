from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.mcp.server import MCPServer
router = APIRouter()
mcp_server = MCPServer()
@router.websocket('/mcp')
async def mcp(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            msg = await websocket.receive_json()
            await websocket.send_json(await mcp_server.handle_message(msg))
    except WebSocketDisconnect:
        pass
