"""Verify the documentation against the codebase (capability map U8).

The truth pass that opened this series existed because the parity doc claimed
things the code did not do. These checkers are the automated version of that
audit. There are three, in order of how much they can prove:

1. :func:`check_parity_doc` — for every ``FEATURE_PARITY.md`` row marked
   shipped, the concrete references in its "Where" column must resolve.
2. :func:`check_doc_references` — the same resolution check over *any*
   document, not just shipped rows. Catches documentation rot: a doc citing a
   module, route or setting that has since been renamed or deleted.
3. :func:`check_absence_claims` — a document saying a named symbol is unused
   or unenforced, when that symbol is live in the code. This is the narrow
   class of stale claim that bit twice: ``OWASP_LLM_MAPPING.md`` said
   ``QueuedTask.max_cost_usd`` was unused for a month after U7 wired it.

Three kinds of reference can be checked mechanically, and only these are
checked:

- **Files** — ``backend/app/agents/chat_tools.py``, ``memory/hybrid_search.py``
  (the docs mix repo-root- and package-relative paths; both are tried).
- **HTTP/WS routes** — ``POST /api/goals/{id}/resume``. Path parameter names
  are normalised away, since the docs name them loosely.
- **Settings** — ``GOAL_MAX_COST_USD`` must exist on the Settings model.

Everything else in backticks (slash-commands like ``/status``, tool names,
protocol tokens, UI strings) is deliberately ignored. A checker that files
GitHub issues has to be conservative: a false positive costs a human's
attention and teaches them to ignore it, so this only reports what it can
prove.

**What none of this catches.** A prose claim with no symbol in it is not
checkable here. Of the three stale claims found in the July 2026 docs sweep,
only one — the ``max_cost_usd`` one — had a name a machine could resolve.
"Ollama/vLLM inference" and "the triple extractor is not yet run on chat
turns" were wrong about behaviour, in sentences naming nothing that exists or
does not. Those still need a human, and pretending otherwise would be the same
kind of overclaim this module was written to catch.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
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
_SOURCE_SUFFIXES = (
    ".py", ".jsx", ".js", ".ts", ".tsx", ".css", ".md", ".yml", ".yaml", ".sql", ".sh",
)
# Roots the doc's file references may be relative to.
_PATH_ROOTS = ("", "backend", "backend/app")

# A line that denies something exists must not be read as a claim that it does.
# "vLLM itself is not a dependency", "Delete `backend/app/zorali.py`", "the
# stubs were deleted in the truth pass" — all legitimate, all would otherwise
# produce a finding for the very thing they are reporting as absent.
_NEGATION_RE = re.compile(
    r"\b(no longer|not a dependency|does not exist|do not exist|deliberately not|"
    r"never (?:built|exists?|implemented)|was deleted|were deleted|unreferenced|"
    r"dead code|delete|removed|absent|unwired|is not (?:in|a) |does not)\b",
    re.IGNORECASE,
)

# Phrases asserting that a named thing is inert. Narrow on purpose: each one
# has to be something a doc would only write about a symbol it believes dead.
_ABSENCE_CLAIM_RE = re.compile(
    r"\b(is unused|are unused|is not enforced|are not enforced|not yet enforced|"
    r"is not wired|is unwired|is dead code|is not implemented|not yet run|"
    r"currently dead)\b",
    re.IGNORECASE,
)
# An identifier a doc might name: `max_cost_usd`, `QueuedTask.max_cost_usd`.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
# A symbol living in this many separate files is being used, not just declared.
_LIVE_FILE_THRESHOLD = 2


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


def _iter_prose_lines(doc_path: Path):
    """Yield (line_number, line) for prose, skipping fenced code blocks.

    Fenced blocks hold example commands and config, where a path is an
    illustration rather than a claim about this repository.
    """
    in_fence = False
    for number, line in enumerate(doc_path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield number, line


def check_doc_references(
    doc_path: Path,
    *,
    repo_root: Path,
    routes: set[str],
    setting_names: set[str],
) -> list[ParityFinding]:
    """Every file, route and setting a document cites must resolve.

    Unlike :func:`check_parity_doc` this reads the whole document rather than
    shipped table rows, so it covers prose docs. Lines that deny something
    exists are skipped — a doc reporting that a module was deleted should not
    be told the module is missing.
    """
    if not doc_path.exists():
        return [ParityFinding(
            kind="missing_file", feature=doc_path.name, reference=str(doc_path),
            detail="The document is missing.",
        )]

    normalized_routes = {normalize_route(r) for r in routes}
    findings: list[ParityFinding] = []
    label = doc_path.name

    for number, line in _iter_prose_lines(doc_path):
        if _NEGATION_RE.search(line):
            continue
        for raw in _BACKTICK_RE.findall(line):
            classified = _classify(raw)
            if classified is None:
                continue
            kind, value = classified
            where = f"{label}:{number}"
            if kind == "file" and not _file_exists(repo_root, value):
                findings.append(ParityFinding(
                    kind="missing_file", feature=label, reference=value,
                    detail=f"{where} cites {value}, which does not exist.",
                ))
            elif kind == "route" and value not in normalized_routes:
                findings.append(ParityFinding(
                    kind="missing_route", feature=label, reference=value,
                    detail=f"{where} cites route {value}, which is not registered on the app.",
                ))
            elif (
                kind == "setting"
                and value not in setting_names
                # SCREAMING_SNAKE also spells enum members and module constants
                # — `ON_DEMAND` is an ExecutionMode, not a setting. If the name
                # exists in the source at all, the doc is naming something real
                # and this checker has nothing to prove.
                and not _symbol_files(repo_root, value)
            ):
                findings.append(ParityFinding(
                    kind="missing_setting", feature=label, reference=value,
                    detail=f"{where} cites setting {value}, which is not defined in Settings "
                           "and does not exist in the source.",
                ))
    return findings


@lru_cache(maxsize=8)
def _source_files(repo_root: str) -> tuple[tuple[str, str], ...]:
    """(path, text) for every backend source file, read once per run."""
    files = []
    for path in sorted((Path(repo_root) / "backend" / "app").rglob("*.py")):
        try:
            files.append((str(path), path.read_text(encoding="utf-8")))
        except OSError:
            continue
    return tuple(files)


def _symbol_files(repo_root: Path, symbol: str) -> set[str]:
    """Source files mentioning a symbol's final segment."""
    name = symbol.rsplit(".", 1)[-1]
    if not name:
        return set()
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    return {
        path for path, text in _source_files(str(repo_root)) if pattern.search(text)
    }


def check_absence_claims(
    doc_path: Path,
    *,
    repo_root: Path,
    setting_names: set[str],
) -> list[ParityFinding]:
    """A document calling a symbol unused, when the code uses it.

    The inverse of an overclaim, and the one the docs actually got wrong:
    something gets wired and the note saying it is not wired outlives it. A
    symbol appearing in two or more source files is being used rather than
    merely declared, which is the signal this trusts.
    """
    if not doc_path.exists():
        return []

    findings: list[ParityFinding] = []
    label = doc_path.name

    for number, line in _iter_prose_lines(doc_path):
        if not _ABSENCE_CLAIM_RE.search(line):
            continue
        for raw in _BACKTICK_RE.findall(line):
            ref = raw.strip()
            if not _IDENTIFIER_RE.match(ref):
                continue
            if ref.upper() in setting_names and ref.isupper():
                # A setting named as disabled is a claim about its value, not
                # about whether the code reads it.
                continue
            if len(_symbol_files(repo_root, ref)) >= _LIVE_FILE_THRESHOLD:
                findings.append(ParityFinding(
                    kind="stale_absence_claim", feature=label, reference=ref,
                    detail=(
                        f"{label}:{number} says {ref} is unused or unenforced, but it "
                        "appears in multiple source files. Either the claim is stale or "
                        "the symbol is dead and should go."
                    ),
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
