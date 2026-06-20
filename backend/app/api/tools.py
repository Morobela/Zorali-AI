from fastapi import APIRouter
from app.core.rbac import user_or_above
from app.tools.registry import get_all_tools

router = APIRouter(prefix='/api/tools')


@router.get('')
async def tools(_user=user_or_above):
    return {'tools': list(get_all_tools().keys())}
