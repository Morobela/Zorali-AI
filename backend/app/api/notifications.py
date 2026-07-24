"""Read/unread API for proactive notifications (capability map U4).

Rows are created by background routines (the reality engine), never through
this router — it only lets the owner see and acknowledge them.
"""
from fastapi import APIRouter

from app.core.rbac import user_or_above
from app.db.repositories import repo

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(unread_only: bool = False, limit: int = 50, _user=user_or_above):
    return await repo.list_notifications(
        owner_id=_user["sub"], unread_only=unread_only, limit=max(1, min(limit, 200))
    )


@router.get("/unread-count")
async def unread_count(_user=user_or_above):
    return {"unread": await repo.unread_notification_count(owner_id=_user["sub"])}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: str, _user=user_or_above):
    return {"read": await repo.mark_notification_read(notification_id, owner_id=_user["sub"])}


@router.post("/read-all")
async def mark_all_read(_user=user_or_above):
    return {"marked": await repo.mark_all_notifications_read(owner_id=_user["sub"])}
