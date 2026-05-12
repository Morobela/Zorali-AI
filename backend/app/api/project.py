from fastapi import APIRouter, Query
from app.core.config import settings
from app.reality.project_scanner import status_report

router = APIRouter(prefix="/api/project")

@router.get("/status")
async def project_status(path: str = Query(default=None)):
    return status_report(path or settings.project_root)
