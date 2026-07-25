"""GitHub repository importer (capability map U6).

Clones a repository into a temporary directory and streams its text files
through the existing ``save_file`` → extract → chunk → index pipeline, so an
imported repo is searchable exactly like an uploaded document. Progress and
per-file outcomes are recorded on the owner-scoped ``repo_imports`` row.

Security posture — this endpoint makes the server fetch a URL, so the input
is treated as hostile:

- Only ``github.com`` repositories are accepted, and ``owner/repo`` must match
  a strict character class. Nothing else is reachable: no other host, no
  scp-style syntax, no local paths, no query strings. That is the SSRF gate.
- ``git`` is invoked with an argument list (never a shell), with terminal
  prompts and system config disabled, without submodules, and under a timeout.
- A token, if supplied, lives only in the clone URL of that one subprocess
  and inside the temporary clone, which is always deleted. It is never
  logged, never stored, and scrubbed from any error text that escapes.
- Files are filtered by extension, size, and content sniffing, with a ceiling
  on how many are imported, so one call cannot exhaust the disk.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
from pathlib import Path

from app.core.config import settings
from app.db.repositories import repo

_log = logging.getLogger(__name__)

# owner/repo: GitHub's own character class. No slashes beyond the single
# separator, so a path or URL can never be smuggled through.
_SEGMENT = r"[A-Za-z0-9_.-]+"
REPO_RE = re.compile(rf"^(?P<owner>{_SEGMENT})/(?P<repo>{_SEGMENT})$")
_GITHUB_URL_RE = re.compile(
    rf"^https://(?:www\.)?github\.com/(?P<owner>{_SEGMENT})/(?P<repo>{_SEGMENT})/?$"
)
# A ref is used as a git argument; keep it to safe characters and never let it
# start with "-" (which git would read as an option).
REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,255}$")

# Directories never worth importing: build output, dependencies, VCS metadata.
IGNORED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".nuxt", "target", "vendor", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "coverage", "htmlcov", ".idea", ".vscode",
    "site-packages", ".terraform", "Pods", ".gradle",
}

# Extensions worth indexing. Kept in step with the upload allowlist, minus the
# formats that only make sense as uploads.
SOURCE_EXTS = {
    ".txt", ".md", ".rst", ".json", ".csv", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".html", ".css", ".scss", ".toml", ".yaml", ".yml", ".xml", ".sh", ".sql",
    ".go", ".rs", ".java", ".kt", ".rb", ".php", ".c", ".h", ".cpp", ".hpp",
    ".cs", ".swift", ".ini", ".cfg", ".dockerfile", ".tf",
}
# Extensionless files that are still worth reading.
SOURCE_NAMES = {"Dockerfile", "Makefile", "README", "LICENSE", "CHANGELOG", ".env.example"}

# Machine-generated manifests: enormous, and they crowd real source out of
# retrieval results without ever answering a question about the code.
IGNORED_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Cargo.lock", "composer.lock", "Gemfile.lock", "go.sum",
}


class ImportError_(ValueError):
    """Rejected import request (surfaced as a 400)."""


def parse_repo(source: str) -> tuple[str, str]:
    """``owner/repo`` or a github.com URL → ``(owner, repo)``.

    Raises ``ImportError_`` for anything else, which is what keeps this
    endpoint from being a general-purpose URL fetcher.
    """
    candidate = (source or "").strip()
    if not candidate:
        raise ImportError_("A repository is required, as 'owner/repo' or a github.com URL")

    url_match = _GITHUB_URL_RE.match(candidate)
    if url_match:
        owner, name = url_match.group("owner"), url_match.group("repo")
    else:
        plain = REPO_RE.match(candidate)
        if not plain:
            raise ImportError_(
                "Only github.com repositories are supported, as 'owner/repo' "
                "or 'https://github.com/owner/repo'"
            )
        owner, name = plain.group("owner"), plain.group("repo")

    name = name[:-4] if name.endswith(".git") else name
    # ".." would be a valid character sequence for the class above.
    for part in (owner, name):
        if part in (".", "..") or not part:
            raise ImportError_("Invalid repository name")
    return owner, name


def validate_ref(ref: str | None) -> str:
    if not ref:
        return ""
    candidate = ref.strip()
    if candidate.startswith("-") or not REF_RE.match(candidate):
        raise ImportError_("Invalid branch or tag name")
    return candidate


def _scrub(text: str, token: str | None) -> str:
    """Error text with any credential removed."""
    cleaned = text
    if token:
        cleaned = cleaned.replace(token, "***")
    # Belt and braces: strip any user:pass@ that git echoed back.
    return re.sub(r"https://[^\s@/]+:[^\s@/]+@", "https://***@", cleaned)


async def clone_repo(owner: str, name: str, ref: str, token: str | None, dest: Path) -> None:
    """Shallow-clone a GitHub repository into ``dest``.

    Split out as the single seam where the network is touched, so tests can
    substitute a local clone and exercise everything else for real.
    """
    url = f"https://github.com/{owner}/{name}.git"
    if token:
        url = f"https://x-access-token:{token}@github.com/{owner}/{name}.git"

    args = [
        "git", "-c", "core.hooksPath=/dev/null",
        "clone", "--depth", "1", "--single-branch", "--no-tags",
        "--recurse-submodules=no",
    ]
    if ref:
        args += ["--branch", ref]
    args += ["--", url, str(dest)]

    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "GIT_TERMINAL_PROMPT": "0",   # never block waiting for credentials
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": str(dest.parent),     # ignore the server user's git config
    }
    proc = await asyncio.create_subprocess_exec(
        *args, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=settings.import_clone_timeout_seconds
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        raise ImportError_("Clone timed out") from exc
    if proc.returncode != 0:
        detail = _scrub(stderr.decode(errors="replace").strip(), token)[:400]
        raise ImportError_(f"Clone failed: {detail or 'unknown git error'}")


def _is_ignored(rel: Path) -> bool:
    return any(part in IGNORED_DIRS for part in rel.parts[:-1]) or rel.name in IGNORED_DIRS


def _is_source_file(rel: Path) -> bool:
    if rel.name in SOURCE_NAMES:
        return True
    suffix = rel.suffix.lower()
    if suffix in SOURCE_EXTS:
        return True
    # Dockerfile.dev, Makefile.local, …
    return rel.name.split(".")[0] in SOURCE_NAMES


def collect_files(root: Path) -> tuple[list[Path], list[dict]]:
    """Walk a clone → (files to import, skip records).

    Deterministic ordering (sorted) so an import is reproducible and a file
    cap always cuts the same way.
    """
    max_bytes = settings.import_max_file_kb * 1024
    selected: list[Path] = []
    skipped: list[dict] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root)
        if _is_ignored(rel):
            continue
        if rel.name in IGNORED_NAMES:
            skipped.append({"path": str(rel), "status": "skipped", "reason": "lockfile"})
            continue
        if not _is_source_file(rel):
            skipped.append({"path": str(rel), "status": "skipped", "reason": "unsupported type"})
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size == 0:
            skipped.append({"path": str(rel), "status": "skipped", "reason": "empty"})
            continue
        if size > max_bytes:
            skipped.append({
                "path": str(rel), "status": "skipped",
                "reason": f"larger than {settings.import_max_file_kb} KB",
            })
            continue
        if len(selected) >= settings.import_max_files:
            skipped.append({
                "path": str(rel), "status": "skipped",
                "reason": f"file cap reached ({settings.import_max_files})",
            })
            continue
        selected.append(rel)

    return selected, skipped


def _looks_binary(raw: bytes) -> bool:
    """A NUL byte in the first block is the classic binary tell."""
    return b"\x00" in raw[:4096]


async def run_import(
    import_id: str,
    *,
    owner: str,
    name: str,
    ref: str,
    token: str | None,
    project_id: str,
    owner_id: str,
) -> dict:
    """Clone, filter and ingest — the background half of an import.

    Never raises: every failure is recorded on the import row, because the
    caller polls that row rather than awaiting this coroutine.
    """
    # Imported here to avoid a circular import at module load (api.files
    # imports nothing from this module, but it does own the pipeline).
    from app.api.files import _ingest_file_background

    tmp_root = Path(tempfile.mkdtemp(prefix="zorali-import-"))
    clone_dir = tmp_root / "repo"
    entries: list[dict] = []
    imported = failed = 0
    try:
        await repo.update_import(import_id, owner_id=owner_id, status="cloning")
        await clone_repo(owner, name, ref, token, clone_dir)

        selected, skipped = collect_files(clone_dir)
        await repo.update_import(
            import_id, owner_id=owner_id, status="importing", skipped_files=len(skipped),
        )

        for rel in selected:
            try:
                raw = (clone_dir / rel).read_bytes()
                if _looks_binary(raw):
                    skipped.append({"path": str(rel), "status": "skipped", "reason": "binary"})
                    continue
                record = await repo.save_file(
                    project_id=project_id, filename=str(rel), content=raw,
                    extracted_text="", chunks=[], indexing_status="queued",
                    owner_id=owner_id,
                )
                # Same pipeline as an upload: extract → chunk → embed → ready.
                # Count what actually indexed — a file that failed extraction
                # is not "imported" just because a row exists for it.
                if await _ingest_file_background(record["id"], str(rel), raw):
                    imported += 1
                    entries.append({"path": str(rel), "status": "imported", "file_id": record["id"]})
                else:
                    failed += 1
                    entries.append({
                        "path": str(rel), "status": "failed", "reason": "could not extract text",
                    })
            except Exception as exc:  # one bad file must not end the import
                failed += 1
                entries.append({
                    "path": str(rel), "status": "failed",
                    "reason": _scrub(str(exc), token)[:200],
                })
            if imported % 25 == 0:
                await repo.update_import(
                    import_id, owner_id=owner_id, imported_files=imported, failed_files=failed,
                )

        capped = (entries + skipped)[: settings.import_max_recorded_files]
        return await repo.update_import(
            import_id, owner_id=owner_id, status="completed",
            imported_files=imported, skipped_files=len(skipped), failed_files=failed,
            files=capped,
        ) or {}
    except ImportError_ as exc:
        return await repo.update_import(
            import_id, owner_id=owner_id, status="failed",
            error=_scrub(str(exc), token)[:500],
            imported_files=imported, failed_files=failed,
        ) or {}
    except Exception as exc:
        _log.warning("Repository import %s failed: %s", import_id, type(exc).__name__)
        return await repo.update_import(
            import_id, owner_id=owner_id, status="failed",
            error=_scrub(f"{type(exc).__name__}: {exc}", token)[:500],
            imported_files=imported, failed_files=failed,
        ) or {}
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
