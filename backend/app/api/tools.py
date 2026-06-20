from fastapi import APIRouter, Depends
from app.core.rbac import user_or_above
from app.tools.registry import get_all_tools

router = APIRouter(prefix='/api/tools')


@router.get('')
async def tools(_user=Depends(user_or_above)):
    return {'tools': list(get_all_tools().keys())}
