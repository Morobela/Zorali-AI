import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from app.db.repositories import repo
from app.core.config import settings

_log = logging.getLogger(__name__)

router = APIRouter(prefix='/api/files')

TEXT_EXTS = {'.txt', '.md', '.json', '.csv', '.py', '.js', '.ts', '.html', '.css', '.jsx', '.tsx', '.toml', '.yaml', '.yml', '.xml', '.sh', '.pdf'}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


def extract_text(filename: str, content: bytes) -> str:
    lower = filename.lower()
    if lower.endswith('.pdf'):
        try:
            raw_str = content.decode('latin-1', errors='replace')
            import re
            text_parts = re.findall(r'\(([^\)]{1,400})\)', raw_str)
            extracted = ' '.join(text_parts)
            if len(extracted.strip()) < 20:
                return '[PDF uploaded — native text extraction not yet available. Install pypdf for full support.]'
            return extracted
        except Exception:
            return '[PDF uploaded — could not extract text.]'
    for ext in TEXT_EXTS:
        if lower.endswith(ext):
            return content.decode('utf-8', errors='ignore')
    raise HTTPException(status_code=400, detail=f'Unsupported file type: {Path(filename).suffix}')


def chunk_text(text: str, size: int = 700, overlap: int = 100):
    """Split text into overlapping chunks for retrieval."""
    chunks = []
    idx = 0
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        chunks.append({'id': idx, 'text': text[start:end]})
        idx += 1
        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start
    return chunks


def _public_file(record: dict) -> dict:
    """Strip internal-only fields from a file record before returning to API callers.

    Embeddings are large float arrays that belong in the retrieval layer; they
    must never appear in API responses. Internal file-system paths are also
    excluded for security.
    """
    public_chunks = [
        {"id": c["id"], "text": c["text"]}
        for c in record.get("chunks", [])
    ]
    return {
        "id": record["id"],
        "project_id": record["project_id"],
        "filename": record["filename"],
        "chunks": public_chunks,
        "created_at": record.get("created_at"),
    }


@router.post('/upload')
async def upload(project_id: str = Query(...), file: UploadFile = File(...)):
    safe_name = Path(file.filename or '').name
    if safe_name != (file.filename or ''):
        raise HTTPException(status_code=400, detail='Invalid filename')
    if safe_name.startswith('.'):
        raise HTTPException(status_code=400, detail='Hidden files are blocked')
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail='File too large (max 5 MB)')
    text = extract_text(safe_name, raw)
    chunks = chunk_text(text)

    # Pre-compute and store per-chunk embeddings at upload time.
    # Uses the Nomic "search_document:" task prefix so the vectors are in the
    # correct space for asymmetric retrieval. Model name is stored alongside
    # each vector so stale embeddings from a different model can be detected.
    if settings.rag_embeddings_enabled:
        try:
            from app.memory.embeddings import embed_texts
            from app.memory.hybrid_search import _document_keywords
            doc_keywords = _document_keywords(text)
            header = f"{safe_name} :: {' '.join(doc_keywords)}"
            search_texts = [f"{header}\n{c['text']}" for c in chunks]
            vectors = await embed_texts(search_texts, task="document")
            if vectors and len(vectors) == len(chunks):
                for chunk, vec in zip(chunks, vectors):
                    chunk["embedding"] = vec
                    chunk["embedding_model"] = settings.rag_embedding_model
        except Exception as exc:
            _log.warning("Embedding generation skipped at upload: %s", exc)

    try:
        record = repo.save_file(
            project_id=project_id, filename=safe_name, content=raw,
            extracted_text=text, chunks=chunks,
        )
        return _public_file(record)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/search')
async def search(project_id: str = Query(...), q: str = Query(...), limit: int = 5):
    """Search file chunks via the hybrid retrieval engine (uses dense embeddings when available)."""
    from app.memory.retrieval import hybrid_retriever
    return await hybrid_retriever.retrieve(q, top_k=limit, project_id=project_id)


@router.get('/list')
async def list_files(project_id: str = Query(...)):
    return [_public_file(f) for f in repo.list_files(project_id)]


@router.delete('/{file_id}')
async def delete_file(file_id: str):
    deleted = repo.delete_file(file_id)
    if not deleted:
        raise HTTPException(status_code=404, detail='File not found')
    return {'deleted': file_id}
