"""The nightly self-check's documentation audit (capability map U8).

The docs sweep that prompted this found three stale claims, all in files the
parity checker never read. These tests pin what the extended checkers do catch
— and one of them replays the real bug verbatim.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.selfcheck.parity_checker import (
    app_routes,
    check_absence_claims,
    check_doc_references,
    settings_names,
)
from app.selfcheck.runner import AUDITED_DOCS, REPO_ROOT, check_docs

ROUTES = {"/api/goals", "/api/goals/{goal_id}/resume"}
SETTINGS = {"GOAL_MAX_COST_USD", "BACKUP_ENABLED"}


def write(tmp_path: Path, text: str) -> Path:
    doc = tmp_path / "SAMPLE.md"
    doc.write_text(text)
    return doc


def references(doc: Path, repo_root: Path) -> list:
    return check_doc_references(
        doc, repo_root=repo_root, routes=ROUTES, setting_names=SETTINGS
    )


# ── broken references ────────────────────────────────────────────────────────

def test_catches_a_cited_file_that_does_not_exist(tmp_path: Path) -> None:
    doc = write(tmp_path, "State lives in `backend/app/agents/ghost_engine.py`.\n")

    found = references(doc, tmp_path)

    assert [f.kind for f in found] == ["missing_file"]
    assert "ghost_engine.py" in found[0].reference


def test_catches_a_cited_route_that_is_not_registered(tmp_path: Path) -> None:
    doc = write(tmp_path, "Resume with `POST /api/goals/{id}/unpause`.\n")

    found = references(doc, tmp_path)

    assert [f.kind for f in found] == ["missing_route"]


def test_catches_a_cited_setting_that_does_not_exist(tmp_path: Path) -> None:
    doc = write(tmp_path, "Bounded by `GOAL_MAX_SPEND_LIMIT`.\n")

    found = references(doc, tmp_path)

    assert [f.kind for f in found] == ["missing_setting"]


def test_a_real_symbol_is_not_reported_as_a_missing_setting(tmp_path: Path) -> None:
    # ON_DEMAND is an ExecutionMode member, not a setting. Filing a nightly
    # issue for naming an enum would teach people to ignore the channel.
    doc = write(tmp_path, "Submitted as `ON_DEMAND` work.\n")

    assert references(doc, REPO_ROOT) == []


# ── things that must not be reported ─────────────────────────────────────────

def test_a_line_denying_something_exists_is_not_a_claim_that_it_does(tmp_path: Path) -> None:
    doc = write(tmp_path, "Delete `backend/app/zorali.py` — nothing imports it.\n")

    assert references(doc, tmp_path) == []


def test_references_inside_fenced_code_blocks_are_ignored(tmp_path: Path) -> None:
    doc = write(tmp_path, "Run it:\n\n```bash\ncat `backend/app/not_real.py`\n```\n")

    assert references(doc, tmp_path) == []


def test_a_missing_document_is_itself_a_finding(tmp_path: Path) -> None:
    found = check_doc_references(
        tmp_path / "GONE.md", repo_root=tmp_path, routes=ROUTES, setting_names=SETTINGS
    )

    assert [f.kind for f in found] == ["missing_file"]


# ── stale absence claims ─────────────────────────────────────────────────────

def test_catches_the_bug_that_prompted_this(tmp_path: Path) -> None:
    # Verbatim from docs/governance/OWASP_LLM_MAPPING.md, which said this for
    # a month after U7 wired the field.
    doc = write(
        tmp_path,
        "| LLM10 | per-task cost budgets are **not** yet enforced "
        "(`QueuedTask.max_cost_usd` is unused — capability map U7) |\n",
    )

    found = check_absence_claims(doc, repo_root=REPO_ROOT, setting_names=settings_names())

    assert [f.kind for f in found] == ["stale_absence_claim"]
    assert found[0].reference == "QueuedTask.max_cost_usd"


def test_an_accurate_absence_claim_is_left_alone(tmp_path: Path) -> None:
    doc = write(tmp_path, "`imaginary_subsystem` is not wired.\n")

    found = check_absence_claims(doc, repo_root=REPO_ROOT, setting_names=settings_names())

    assert found == []


def test_a_setting_described_as_off_is_not_an_absence_claim(tmp_path: Path) -> None:
    # "not enforced" about a flag's *value* is a different statement from
    # "the code never reads this".
    doc = write(tmp_path, "`CODE_EXECUTION_ENABLED` is not enforced when false.\n")

    found = check_absence_claims(doc, repo_root=REPO_ROOT, setting_names=settings_names())

    assert found == []


# ── the shipped docs ─────────────────────────────────────────────────────────

def test_every_audited_document_exists() -> None:
    missing = [name for name in AUDITED_DOCS if not (REPO_ROOT / name).exists()]

    assert missing == [], f"AUDITED_DOCS names files that are not there: {missing}"


def test_the_shipped_docs_are_clean() -> None:
    """CI enforces what the nightly run reports.

    Without this the checker only complains at 03:00 UTC, by which point the
    change that broke a reference is already merged.
    """
    findings = check_docs()

    assert findings == [], "\n".join(f.detail.splitlines()[0] for f in findings)


@pytest.mark.parametrize("doc_name", AUDITED_DOCS)
def test_each_audited_document_individually(doc_name: str) -> None:
    # Parametrised so a failure names the document rather than the whole set.
    doc = REPO_ROOT / doc_name
    found = check_doc_references(
        doc, repo_root=REPO_ROOT, routes=app_routes(), setting_names=settings_names()
    )

    assert found == [], "\n".join(f.detail for f in found)
