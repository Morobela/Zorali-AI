from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from app.db.repositories import repo

router = APIRouter(prefix='/api/files')

TEXT_EXTS = {'.txt', '.md', '.json', '.csv', '.py', '.js', '.ts', '.html', '.css'}


def extract_text(filename: str, content: bytes) -> str:
    lower = filename.lower()
    for ext in TEXT_EXTS:
        if lower.endswith(ext):
            return content.decode('utf-8', errors='ignore')
    if lower.endswith('.pdf'):
        raise HTTPException(status_code=400, detail='PDF extraction not enabled in this build')
    raise HTTPException(status_code=400, detail='Unsupported file type')


def chunk_text(text: str, size: int = 700, overlap: int = 100):
    chunks = []
    idx = 0
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        chunks.append({'id': idx, 'text': text[start:end]})
        idx += 1
        start = max(end - overlap, end)
    return chunks


@router.post('/upload')
async def upload(project_id: str = Query(...), file: UploadFile = File(...)):
    raw = await file.read()
    text = extract_text(file.filename, raw)
    chunks = chunk_text(text)
    try:
        return repo.save_file(project_id=project_id, filename=file.filename, content=raw, extracted_text=text, chunks=chunks)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/search')
async def search(project_id: str = Query(...), q: str = Query(...), limit: int = 5):
    return repo.search_chunks(project_id, q, limit)


@router.get('/list')
async def list_files(project_id: str = Query(...)):
    return repo.list_files(project_id)
