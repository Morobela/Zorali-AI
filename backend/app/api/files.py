from fastapi import APIRouter, Query
from app.tools.file_tools import read_file
router = APIRouter(prefix='/api/files')
@router.get('/read')
async def read(path: str = Query(...)):
    return {'path': path, 'content': await read_file(path)}
