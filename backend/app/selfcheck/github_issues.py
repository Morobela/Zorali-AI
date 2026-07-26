"""Issue filing for the nightly self-check (capability map U8).

**This module is the entire write surface of self-improvement, and it can do
exactly one thing: open an issue.** There is no code here to create a branch,
push a commit, open a pull request, or merge anything — not disabled by a
flag, absent. Phase two of U8 (proposing patches as branches gated on CI) is
deliberately not implemented, and the map's design rule is why: Ultron becomes
stoppable the moment Vision cuts his network access, so in this architecture
the human permanently holds merge authority, by construction rather than by
configuration.

Filing is also idempotent. The nightly run would otherwise re-file the same
finding every night; each issue carries a stable marker and existing open
issues are searched for it first.
"""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

_log = logging.getLogger(__name__)

API_ROOT = "https://api.github.com"
_TIMEOUT_S = 20.0
# Every issue this module opens is tagged so it can be found again (dedupe)
# and recognised as machine-filed by a human reading the tracker.
MARKER_PREFIX = "zorali-selfcheck"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def marker_for(key: str) -> str:
    """The stable identifier embedded in an issue body for deduplication."""
    return f"<!-- {MARKER_PREFIX}:{key} -->"


def can_file() -> bool:
    """Whether issue filing is possible: a token and a repository are needed."""
    return bool(settings.github_token and settings.github_repo)


async def find_open_issue(key: str) -> int | None:
    """Number of an already-open issue for this finding, if any."""
    if not can_file():
        return None
    query = f'repo:{settings.github_repo} is:issue is:open in:body "{MARKER_PREFIX}:{key}"'
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.get(
                f"{API_ROOT}/search/issues", headers=_headers(), params={"q": query, "per_page": 1}
            )
        if resp.status_code != 200:
            return None
        items = resp.json().get("items") or []
        return items[0]["number"] if items else None
    except Exception as exc:
        _log.info("Issue search failed: %s", type(exc).__name__)
        return None


async def create_issue(title: str, body: str, key: str, labels: list[str] | None = None) -> int | None:
    """Open one issue. Returns its number, or None when filing was not possible.

    The only GitHub write this codebase performs.
    """
    if not can_file():
        return None
    payload = {
        "title": title[:250],
        "body": f"{body}\n\n{marker_for(key)}",
        "labels": labels or ["zorali-selfcheck"],
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.post(
                f"{API_ROOT}/repos/{settings.github_repo}/issues",
                headers=_headers(), json=payload,
            )
        if resp.status_code not in (200, 201):
            _log.warning("Could not file issue (%s): %s", resp.status_code, resp.text[:200])
            return None
        return resp.json().get("number")
    except Exception as exc:
        _log.warning("Issue filing failed: %s", type(exc).__name__)
        return None


async def file_once(title: str, body: str, key: str) -> tuple[int | None, bool]:
    """File an issue unless one is already open for this finding.

    Returns ``(issue_number, created)``.
    """
    existing = await find_open_issue(key)
    if existing is not None:
        return existing, False
    return await create_issue(title, body, key), True
