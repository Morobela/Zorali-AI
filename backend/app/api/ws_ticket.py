from fastapi import APIRouter, HTTPException

from app.core.rbac import any_authenticated
from app.core.tickets import TICKET_TTL_SECONDS, issue_ticket

router = APIRouter(prefix="/api")


@router.post("/ws-ticket")
async def create_ws_ticket(user=any_authenticated):
    """Issue a single-use WebSocket auth ticket bound to the caller.

    The client presents it as ``?ticket=`` when opening ``/ws/...`` sockets;
    the backend consumes it on first use. Requires a valid access token —
    exactly the users who could open the socket under the old query-token
    scheme, with no role floor.
    """
    try:
        ticket = await issue_ticket(user)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Ticket store unavailable — cannot open WebSocket sessions right now.",
        ) from exc
    return {"ticket": ticket, "expires_in": TICKET_TTL_SECONDS}
