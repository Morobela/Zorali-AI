"""Git repository state for the configured project root.

Reports branch, ahead/behind counts against the upstream, dirty-file count
and the last commit. Every failure mode (not a repo, no upstream, no
commits, git missing) degrades to ``available: False`` or ``None`` fields
rather than raising: the scanner feeds a background loop that must never
die on a bad worktree.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

_GIT_TIMEOUT_S = 8.0


async def _git(args: list[str], cwd: str) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=_GIT_TIMEOUT_S)
        return proc.returncode or 0, out.decode(errors="replace").strip()
    except Exception:
        return 1, ""


async def scan_git(path: str) -> dict:
    root = str(Path(path))
    unavailable = {
        "available": False, "branch": None, "ahead": None, "behind": None,
        "dirty_files": 0, "last_commit": None,
    }
    if not Path(root).is_dir():
        return unavailable
    code, _ = await _git(["rev-parse", "--is-inside-work-tree"], root)
    if code != 0:
        return unavailable

    _, branch = await _git(["rev-parse", "--abbrev-ref", "HEAD"], root)

    ahead = behind = None
    code, counts = await _git(["rev-list", "--left-right", "--count", "HEAD...@{upstream}"], root)
    if code == 0 and counts:
        left, _, right = counts.partition("\t")
        try:
            ahead, behind = int(left), int(right)
        except ValueError:
            pass

    _, porcelain = await _git(["status", "--porcelain"], root)
    dirty_files = len([line for line in porcelain.splitlines() if line.strip()])

    last_commit = None
    code, log = await _git(["log", "-1", "--format=%H%x1f%ct%x1f%s"], root)
    if code == 0 and log:
        commit_hash, _, rest = log.partition("\x1f")
        committed_at, _, subject = rest.partition("\x1f")
        try:
            last_commit = {"hash": commit_hash, "committed_at": int(committed_at), "subject": subject}
        except ValueError:
            pass

    return {
        "available": True,
        "branch": branch or None,
        "ahead": ahead,
        "behind": behind,
        "dirty_files": dirty_files,
        "last_commit": last_commit,
    }
