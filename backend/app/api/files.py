import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from app.db.repositories import repo
from app.core.config import settings
from app.core.rbac import user_or_above

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
        "indexing_status": record.get("indexing_status", "ready"),
        "created_at": record.get("created_at"),
    }


async def _embed_chunks_background(file_id: str, safe_name: str, text: str, chunks: list[dict]) -> None:
    """Run embedding generation after the upload response has been returned."""
    try:
        from app.memory.embeddings import embed_texts
        from app.memory.hybrid_search import _document_keywords
        await repo.update_file_indexing_status(file_id, "indexing")
        if settings.rag_contextual_enabled:
            doc_keywords = _document_keywords(text)
            header = f"{safe_name} :: {' '.join(doc_keywords)}"
            search_texts = [f"{header}\n{c['text']}" for c in chunks]
        else:
            search_texts = [c["text"] for c in chunks]
        vectors = await embed_texts(search_texts, task="document")
        if vectors and len(vectors) == len(chunks):
            embedded_chunks = []
            for chunk, vec in zip(chunks, vectors):
                embedded_chunks.append({**chunk, "embedding": vec, "embedding_model": settings.rag_embedding_model})
            await repo.update_file_indexing_status(file_id, "ready", chunks=embedded_chunks)
        else:
            await repo.update_file_indexing_status(file_id, "ready")
    except Exception as exc:
        _log.warning("Background embedding failed for %s: %s", file_id, exc)
        await repo.update_file_indexing_status(file_id, "failed")


@router.post('/upload', status_code=202)
async def upload(background_tasks: BackgroundTasks, project_id: str = Query(...), file: UploadFile = File(...), _user=user_or_above):
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

    # Save the file record immediately so the caller gets a file_id back.
    # If embeddings are enabled, the actual Ollama call happens in a background
    # task so the HTTP response is not held open while waiting for GPU inference.
    indexing_status = "queued" if settings.rag_embeddings_enabled else "ready"
    try:
        record = await repo.save_file(
            project_id=project_id, filename=safe_name, content=raw,
            extracted_text=text, chunks=chunks, indexing_status=indexing_status,
            owner_id=_user["sub"],
        )
    except LookupError as exc:
        # Project does not exist or is not owned by this caller — do not leak
        # which by returning 404.
        raise HTTPException(status_code=404, detail='Project not found') from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if settings.rag_embeddings_enabled:
        background_tasks.add_task(_embed_chunks_background, record["id"], safe_name, text, chunks)

    return _public_file(record)


@router.get('/{file_id}/status')
async def file_status(file_id: str, _user=user_or_above):
    """Poll indexing_status for a file after upload (queued → indexing → ready | failed)."""
    record = await repo.get_file(file_id, owner_id=_user["sub"])
    if not record:
        raise HTTPException(status_code=404, detail='File not found')
    return {"id": file_id, "indexing_status": record.get("indexing_status", "ready")}


@router.get('/search')
async def search(project_id: str = Query(...), q: str = Query(...), limit: int = 5, _user=user_or_above):
    """Search file chunks via the hybrid retrieval engine (uses dense embeddings when available)."""
    from app.memory.retrieval import hybrid_retriever
    results = await hybrid_retriever.retrieve(q, top_k=limit, project_id=project_id, owner_id=_user["sub"])
    if results is None:
        raise HTTPException(status_code=404, detail='Project not found')
    return results


@router.get('/list')
async def list_files(project_id: str = Query(...), _user=user_or_above):
    files = await repo.list_files(project_id, owner_id=_user["sub"])
    if files is None:
        raise HTTPException(status_code=404, detail='Project not found')
    return [_public_file(f) for f in files]


@router.delete('/{file_id}')
async def delete_file(file_id: str, _user=user_or_above):
    deleted = await repo.delete_file(file_id, owner_id=_user["sub"])
    if not deleted:
        raise HTTPException(status_code=404, detail='File not found')
    return {'deleted': file_id}
