from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from app.core.tickets import redeem_ticket
from app.mcp.server import MCPServer

router = APIRouter()
mcp_server = MCPServer()


@router.websocket('/mcp')
async def mcp(websocket: WebSocket, ticket: str = Query(default=None)):
    # Single-use ticket auth (POST /api/ws-ticket) — same scheme as /ws/chat;
    # JWTs are never accepted in the URL because query strings get logged.
    user = await redeem_ticket(ticket)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    try:
        while True:
            msg = await websocket.receive_json()
            # Tools execute on behalf of the ticket's user: caller context and
            # role ride into registry.execute, same as the chat tool loop.
            await websocket.send_json(await mcp_server.handle_message(
                msg, caller=user["sub"], caller_role=user.get("role", "user"),
            ))
    except WebSocketDisconnect:
        pass
