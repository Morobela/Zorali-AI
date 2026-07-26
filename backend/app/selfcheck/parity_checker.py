"""Verify FEATURE_PARITY.md claims against the codebase (capability map U8).

The truth pass that opened this series existed because the parity doc claimed
things the code did not do. This checker is the automated version of that
audit: for every row marked shipped, the concrete references in its "Where"
column must actually resolve.

Three kinds of reference can be checked mechanically, and only these are
checked:

- **Files** — ``backend/app/agents/chat_tools.py``, ``memory/hybrid_search.py``
  (the doc mixes repo-root- and package-relative paths; both are tried).
- **HTTP/WS routes** — ``POST /api/goals/{id}/resume``. Path parameter names
  are normalised away, since the doc names them loosely.
- **Settings** — ``GOAL_MAX_COST_USD`` must exist on the Settings model.

Everything else in backticks (slash-commands like ``/status``, tool names,
protocol tokens, UI strings) is deliberately ignored. A checker that files
GitHub issues has to be conservative: a false positive costs a human's
attention and teaches them to ignore it, so this only reports what it can
prove.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# A row of the feature matrix: | Feature | Reference | Status | Where |
_ROW_RE = re.compile(r"^\|(?P<cells>.+)\|\s*$")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_METHOD_RE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|WS)\s+(?P<path>/\S+)$")

SHIPPED_MARK = "✅"
# Only these prefixes are treated as HTTP/WS routes; a leading slash alone is
# not enough (the doc also documents chat slash-commands like `/status`).
_ROUTE_PREFIXES = ("/api/", "/a2a/", "/ws/")
_EXACT_ROUTES = {"/mcp", "/metrics"}
_SOURCE_SUFFIXES = (".py", ".jsx", ".js", ".ts", ".tsx", ".css", ".md", ".yml", ".yaml", ".sql")
# Roots the doc's file references may be relative to.
_PATH_ROOTS = ("", "backend", "backend/app")


@dataclass(frozen=True)
class ParityFinding:
    kind: str          # "missing_file" | "missing_route" | "missing_setting"
    feature: str       # the row's feature name
    reference: str     # the exact reference that did not resolve
    detail: str

    @property
    def key(self) -> str:
        """Stable identity, so the same overclaim is filed once, not nightly."""
        return f"parity:{self.kind}:{self.reference}"


def _split_row(line: str) -> list[str] | None:
    match = _ROW_RE.match(line.strip())
    if not match:
        return None
    cells = [c.strip() for c in match.group("cells").split("|")]
    return cells if len(cells) >= 4 else None


def normalize_route(path: str) -> str:
    """``/api/project/{project_id}/imports`` → ``/api/project/{}/imports``."""
    path = path.split("?", 1)[0].rstrip("/") or "/"
    return re.sub(r"\{[^}]*\}", "{}", path)


def _classify(reference: str) -> tuple[str, str] | None:
    """(kind, value) for a checkable reference, or None to ignore it."""
    ref = reference.strip()
    if not ref:
        return None

    method_match = _METHOD_RE.match(ref)
    candidate = method_match.group("path") if method_match else ref
    if candidate.startswith(_ROUTE_PREFIXES) or candidate in _EXACT_ROUTES:
        return "route", normalize_route(candidate)

    # Settings are SCREAMING_SNAKE_CASE; a bare acronym is not one.
    if re.fullmatch(r"[A-Z][A-Z0-9]*(_[A-Z0-9]+)+", ref):
        return "setting", ref

    if "/" in ref and ref.endswith(_SOURCE_SUFFIXES) and " " not in ref:
        return "file", ref
    return None


def _file_exists(repo_root: Path, relative: str) -> bool:
    return any((repo_root / root / relative).exists() for root in _PATH_ROOTS)


def check_parity_doc(
    doc_path: Path,
    *,
    repo_root: Path,
    routes: set[str],
    setting_names: set[str],
) -> list[ParityFinding]:
    """Every checkable reference in a shipped row must resolve.

    ``routes`` should be the app's registered paths and ``setting_names`` the
    Settings fields (upper-cased); both are passed in so this stays a pure
    function that tests can drive directly.
    """
    if not doc_path.exists():
        return [ParityFinding(
            kind="missing_file", feature="(document)", reference=str(doc_path),
            detail="The parity document itself is missing.",
        )]

    normalized_routes = {normalize_route(r) for r in routes}
    findings: list[ParityFinding] = []

    for line in doc_path.read_text(encoding="utf-8").splitlines():
        cells = _split_row(line)
        if not cells:
            continue
        feature, status, where = cells[0], cells[2], cells[3]
        if SHIPPED_MARK not in status:
            # Only shipped rows are claims; partial/roadmap rows are honest
            # about being incomplete.
            continue

        for raw in _BACKTICK_RE.findall(where):
            classified = _classify(raw)
            if classified is None:
                continue
            kind, value = classified
            if kind == "file" and not _file_exists(repo_root, value):
                findings.append(ParityFinding(
                    kind="missing_file", feature=feature, reference=value,
                    detail=f"'{feature}' is marked shipped and cites {value}, which does not exist.",
                ))
            elif kind == "route" and value not in normalized_routes:
                findings.append(ParityFinding(
                    kind="missing_route", feature=feature, reference=value,
                    detail=f"'{feature}' is marked shipped and cites route {value}, "
                           "which is not registered on the app.",
                ))
            elif kind == "setting" and value not in setting_names:
                findings.append(ParityFinding(
                    kind="missing_setting", feature=feature, reference=value,
                    detail=f"'{feature}' is marked shipped and cites setting {value}, "
                           "which is not defined in Settings.",
                ))
    return findings


def _collect_paths(routes, seen: set[str], depth: int = 0) -> None:
    """Walk a route table, descending into included routers.

    Recent FastAPI keeps ``include_router`` results as wrapper objects rather
    than flattening them into ``app.routes``, so a naive one-level read finds
    only the handful of routes defined on the app itself — which would make
    this checker file issues about routes that exist. Both shapes are handled.
    """
    if depth > 5:
        return
    for route in routes:
        path = getattr(route, "path", "")
        if path:
            seen.add(path)
        nested = getattr(route, "routes", None)
        if nested is None:
            inner = getattr(route, "original_router", None)
            nested = getattr(inner, "routes", None)
        if nested:
            _collect_paths(nested, seen, depth + 1)


def app_routes() -> set[str]:
    """Every path the app serves, HTTP and WebSocket."""
    from app.main import app

    paths: set[str] = set()
    _collect_paths(app.routes, paths)
    # The OpenAPI schema is the public, version-stable source for HTTP routes;
    # the walk above additionally covers WebSocket routes, which it omits.
    try:
        paths.update(app.openapi().get("paths", {}).keys())
    except Exception:
        pass
    return {p for p in paths if p}


def settings_names() -> set[str]:
    """Configuration field names, upper-cased as the docs write them."""
    from app.core.config import Settings

    return {name.upper() for name in Settings.model_fields}
