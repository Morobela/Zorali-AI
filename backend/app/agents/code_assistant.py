from pathlib import Path
from app.core.config import settings


def _read_snippet(path: Path, max_chars: int = 500) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except Exception:
        return ""


async def run_code_assistant(message: str, context: dict) -> dict:
    configured_root = Path(settings.project_root)
    if configured_root.exists():
        project_root = configured_root
    else:
        project_root = Path(__file__).resolve().parents[3]
    files = []
    for p in project_root.rglob("*"):
        if p.is_file() and p.suffix in {".py", ".js", ".jsx", ".ts", ".tsx", ".md"} and "node_modules" not in str(p):
            files.append(p)
        if len(files) >= 8:
            break
    candidates = []
    lower = message.lower()
    for p in files:
        if any(tok in p.name.lower() for tok in lower.split()[:4]):
            candidates.append(p)
    candidates = candidates or files[:3]
    snippets = [{"file": str(p.relative_to(project_root)), "snippet": _read_snippet(p)} for p in candidates]
    error_hint = "Detected possible error report; review stack trace and match against snippets." if "error" in lower or "traceback" in lower else "No explicit error text detected."
    return {
        "agent": "code_assistant",
        "analysis": error_hint,
        "file_snippets": snippets,
        "patch_suggestion": "Proposed patch: update the implicated function, add regression test, and rerun backend suite.",
    }
