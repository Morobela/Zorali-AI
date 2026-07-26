"""Gated self-improvement (capability map U8, phase one).

The DoD: introduce a deliberate parity-doc overclaim; the nightly run files
an issue naming it.

Two properties matter as much as the DoD. First, the checker must not cry
wolf — it runs against the real FEATURE_PARITY.md and must find nothing, or
nobody will read its issues. Second, this feature must never be able to
change code: the guard test at the bottom asserts that the only GitHub write
in the module is opening an issue.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.repositories import repo
from app.main import app
from app.selfcheck import github_issues, runner
from app.selfcheck.parity_checker import (
    app_routes,
    check_parity_doc,
    normalize_route,
    settings_names,
)

client = TestClient(app)

REPO_ROOT = Path(runner.REPO_ROOT)

HEADER = "| Feature | Reference assistant | Zorali status | Where |\n|---|---|---|---|\n"


def _doc(tmp_path: Path, rows: str) -> Path:
    path = tmp_path / "FEATURE_PARITY.md"
    path.write_text(HEADER + rows, encoding="utf-8")
    return path


def _check(doc_path: Path, **overrides):
    kwargs = {
        "repo_root": REPO_ROOT,
        "routes": app_routes(),
        "setting_names": settings_names(),
    }
    kwargs.update(overrides)
    return check_parity_doc(doc_path, **kwargs)


# ── the checker must not cry wolf ────────────────────────────────────────────

def test_the_real_parity_doc_has_no_overclaims():
    """Every shipped row's references resolve against this codebase."""
    findings = _check(REPO_ROOT / "docs" / "FEATURE_PARITY.md")
    assert findings == [], [f.detail for f in findings]


def test_slash_commands_and_prose_are_not_mistaken_for_claims(tmp_path):
    """`/status`, tool names and protocol tokens are not checkable references."""
    doc = _doc(tmp_path, (
        "| Task mode | All | ✅ | `/status`, `/files`, `/read`, `calculator`, "
        "`TOOL_CALL:`, `[W#]`, `+ New chat`, `depends_on: []` |\n"
    ))
    assert _check(doc) == []


def test_route_parameter_names_do_not_matter(tmp_path):
    """The doc writes `{id}` where the app registers `{project_id}`."""
    assert normalize_route("/api/project/{project_id}/imports") == "/api/project/{}/imports"
    assert normalize_route("/api/project/{id}/search?q=") == "/api/project/{}/search"
    doc = _doc(tmp_path, "| Import | X | ✅ | `POST /api/project/{id}/import/github` |\n")
    assert _check(doc) == []


def test_unshipped_rows_are_not_checked(tmp_path):
    """Roadmap and partial rows are honest about being incomplete."""
    doc = _doc(tmp_path, (
        "| Dreaming | X | 🗺 | `backend/app/nonexistent.py`, `NOT_A_SETTING` |\n"
        "| Half done | X | 🟡 | `GET /api/nope` |\n"
    ))
    assert _check(doc) == []


# ── the overclaims it must catch ─────────────────────────────────────────────

def test_missing_file_route_and_setting_are_all_caught(tmp_path):
    doc = _doc(tmp_path, (
        "| Ghost module | X | ✅ | `backend/app/agents/telepathy.py` |\n"
        "| Ghost route | X | ✅ | `POST /api/telepathy/send` |\n"
        "| Ghost setting | X | ✅ | `TELEPATHY_ENABLED` |\n"
    ))
    findings = _check(doc)
    kinds = {f.kind for f in findings}
    assert kinds == {"missing_file", "missing_route", "missing_setting"}
    assert {f.feature for f in findings} == {"Ghost module", "Ghost route", "Ghost setting"}


def test_finding_keys_are_stable_for_deduplication(tmp_path):
    doc = _doc(tmp_path, "| Ghost | X | ✅ | `backend/app/ghost.py` |\n")
    first, second = _check(doc), _check(doc)
    assert [f.key for f in first] == [f.key for f in second]
    assert first[0].key == "parity:missing_file:backend/app/ghost.py"


# ── the U8 definition of done ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deliberate_overclaim_files_an_issue_naming_it(tmp_path, monkeypatch):
    """U8 DoD: an overclaim introduced into the parity doc results in a filed
    GitHub issue that names it — and nothing else is touched."""
    doc = _doc(tmp_path, (
        "| Streaming chat | All | ✅ | WS `/ws/chat/{session}` |\n"
        "| Telepathic input | JARVIS | ✅ | `backend/app/multimodal/telepathy.py` |\n"
    ))

    filed: list[dict] = []

    async def fake_file_once(title, body, key):
        filed.append({"title": title, "body": body, "key": key})
        return 4242, True

    monkeypatch.setattr(github_issues, "file_once", fake_file_once)
    monkeypatch.setattr(runner.github_issues, "file_once", fake_file_once)
    # The suite and ruff are exercised separately; keep this run to the parity
    # check so the DoD is about the overclaim.
    monkeypatch.setattr(runner, "check_lint", lambda: _no_findings())

    before = {n["id"] for n in await repo.list_notifications(owner_id="test-user")}
    result = await runner.run_self_check(run_tests=False, doc_path=doc)

    # Exactly one issue, naming the overclaim.
    assert len(filed) == 1, filed
    issue = filed[0]
    assert "Telepathic input" in issue["title"]
    assert "backend/app/multimodal/telepathy.py" in issue["body"]
    assert "does not exist" in issue["body"]
    assert issue["key"] == "parity:missing_file:backend/app/multimodal/telepathy.py"
    # It says what it did NOT do.
    assert "nothing was changed" in issue["body"].lower()

    # The run is recorded.
    assert result["status"] == "findings"
    assert result["issues_filed"] == 1
    assert result["findings"][0]["kind"] == "parity"

    # And the admins were told, without asking.
    after = await repo.list_notifications(owner_id="test-user")
    fresh = [n for n in after if n["id"] not in before and n["kind"] == "self_check"]
    assert fresh, "a run with findings must notify"
    assert "1 finding" in fresh[0]["title"]

    # The honest row in the same document produced nothing.
    assert all("Streaming chat" not in f["title"] for f in result["findings"])


async def _no_findings():
    return []


@pytest.mark.asyncio
async def test_clean_run_files_nothing_and_stays_quiet(tmp_path, monkeypatch):
    doc = _doc(tmp_path, "| Streaming chat | All | ✅ | WS `/ws/chat/{session}` |\n")
    monkeypatch.setattr(runner, "check_lint", lambda: _no_findings())

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("a clean run must not file anything")

    monkeypatch.setattr(runner.github_issues, "file_once", fail_if_called)

    before = {n["id"] for n in await repo.list_notifications(owner_id="test-user")}
    result = await runner.run_self_check(run_tests=False, doc_path=doc)

    assert result["status"] == "clean"
    assert result["findings"] == []
    after = await repo.list_notifications(owner_id="test-user")
    assert [n for n in after if n["id"] not in before and n["kind"] == "self_check"] == []


@pytest.mark.asyncio
async def test_findings_are_recorded_even_with_no_github_token(tmp_path, monkeypatch):
    """Without a token the run still reports; it just cannot file."""
    monkeypatch.setattr(settings, "github_token", "")
    monkeypatch.setattr(settings, "github_repo", "")
    monkeypatch.setattr(runner, "check_lint", lambda: _no_findings())
    doc = _doc(tmp_path, "| Ghost | X | ✅ | `backend/app/ghost.py` |\n")

    result = await runner.run_self_check(run_tests=False, doc_path=doc)
    assert result["status"] == "findings"
    assert result["issues_filed"] == 0
    notes = await repo.list_notifications(owner_id="test-user")
    assert any("No GitHub token" in n["body"] for n in notes if n["kind"] == "self_check")


@pytest.mark.asyncio
async def test_an_already_open_issue_is_not_filed_again(tmp_path, monkeypatch):
    """The nightly cadence must not re-file the same finding every night."""
    monkeypatch.setattr(settings, "github_token", "t")
    monkeypatch.setattr(settings, "github_repo", "Morobela/Zorali-AI")
    monkeypatch.setattr(runner, "check_lint", lambda: _no_findings())

    searched: list[str] = []

    async def fake_search(key):
        searched.append(key)
        return 99  # already open

    async def fail_create(*args, **kwargs):
        raise AssertionError("must not create a duplicate issue")

    monkeypatch.setattr(github_issues, "find_open_issue", fake_search)
    monkeypatch.setattr(github_issues, "create_issue", fail_create)

    doc = _doc(tmp_path, "| Ghost | X | ✅ | `backend/app/ghost.py` |\n")
    result = await runner.run_self_check(run_tests=False, doc_path=doc)

    assert searched, "an existing issue must be searched for first"
    assert result["status"] == "findings"
    assert result["issues_filed"] == 0, "no NEW issue was created"


# ── lint / test checkers ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failing_lint_becomes_a_finding(monkeypatch):
    async def fake_run(args, *, timeout):
        return 1, "backend/app/x.py:1:1: F401 'os' imported but unused"

    monkeypatch.setattr(runner, "_run_command", fake_run)
    findings = await runner.check_lint()
    assert len(findings) == 1
    assert findings[0].kind == "lint"
    assert "F401" in findings[0].detail
    assert findings[0].key == "lint:ruff"


@pytest.mark.asyncio
async def test_failing_suite_becomes_a_finding(monkeypatch):
    async def fake_run(args, *, timeout):
        return 1, "FAILED tests/backend/test_health.py::test_health_ok"

    monkeypatch.setattr(runner, "_run_command", fake_run)
    findings = await runner.check_tests()
    assert len(findings) == 1 and findings[0].kind == "tests"
    assert "test_health_ok" in findings[0].detail


@pytest.mark.asyncio
async def test_green_checks_produce_no_findings(monkeypatch):
    async def fake_run(args, *, timeout):
        return 0, "All checks passed!"

    monkeypatch.setattr(runner, "_run_command", fake_run)
    assert await runner.check_lint() == []
    assert await runner.check_tests() == []


def test_next_run_is_the_coming_configured_hour():
    from datetime import datetime, timezone

    noon = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc).timestamp()
    assert runner.seconds_until_next_run(noon, 3) == pytest.approx(15 * 3600)
    assert runner.seconds_until_next_run(noon, 13) == pytest.approx(1 * 3600)


# ── the safety invariant ─────────────────────────────────────────────────────

def test_self_improvement_can_only_open_issues():
    """The map's design rule, enforced as a test: merge authority is human by
    construction. The write surface is one endpoint — opening an issue — and
    there is no code here to branch, commit, open a PR, or merge."""
    source = inspect.getsource(github_issues) + inspect.getsource(runner)
    forbidden = ("/pulls", "/merges", "git/refs", "/merge", "auto_merge", "git push")
    for token in forbidden:
        assert token not in source, f"self-improvement must not reference {token!r}"

    # There is exactly one write call in the module, and it opens an issue.
    module_source = inspect.getsource(github_issues)
    assert module_source.count("client.post(") == 1, "only one write call may exist"
    create_source = inspect.getsource(github_issues.create_issue)
    assert "client.post(" in create_source
    assert "/issues" in create_source, "the sole write must target the issues endpoint"


def test_manual_trigger_is_admin_gated_and_off_by_default(monkeypatch):
    monkeypatch.setattr(settings, "self_improvement_enabled", False)
    assert client.post("/api/self-check/run").status_code == 403


@pytest.mark.asyncio
async def test_runs_are_listed_newest_first():
    first = await repo.create_self_check()
    await repo.finish_self_check(first["id"], status="clean", findings=[])
    listed = client.get("/api/self-check?limit=5").json()
    assert listed and listed[0]["id"] == first["id"]
    assert listed[0]["status"] == "clean"
