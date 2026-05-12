from pathlib import Path

SAFE_ROOT = Path('/workspace').resolve()

def _safe(path: str) -> Path:
    p = Path(path).resolve()
    if SAFE_ROOT not in p.parents and p != SAFE_ROOT:
        raise PermissionError('Path outside safe workspace')
    return p

async def read_file(path: str) -> str:
    return _safe(path).read_text(encoding='utf-8', errors='ignore')

async def write_file(path: str, content: str) -> dict:
    p = _safe(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding='utf-8')
    return {'written': str(p), 'bytes': len(content)}
