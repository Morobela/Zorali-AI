from fastapi import APIRouter
from app.tools.registry import get_all_tools
router = APIRouter(prefix='/api/tools')
@router.get('')
async def tools():
    return {'tools': list(get_all_tools().keys())}
