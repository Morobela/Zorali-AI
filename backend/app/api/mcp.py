from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from app.core.auth import decode_token
from app.mcp.server import MCPServer

router = APIRouter()
mcp_server = MCPServer()


@router.websocket('/mcp')
async def mcp(websocket: WebSocket, token: str = Query(default=None)):
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        decode_token(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    try:
        while True:
            msg = await websocket.receive_json()
            await websocket.send_json(await mcp_server.handle_message(msg))
    except WebSocketDisconnect:
        pass
