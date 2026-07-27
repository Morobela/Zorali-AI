"""infra/scripts/sync-env.sh — the migration path for an existing .env.

A deployment copies .env.example once. Every release after that adds settings
it never sees, so the script that carries them across has to keep working;
these tests are what stops it rotting.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "scripts" / "sync-env.sh"

OLD_ENV = """\
SECRET_KEY=a-real-production-secret
POSTGRES_PASSWORD=not-the-default
CLOUD_API_KEY=sk-live-xxxx
WEB_SEARCH_ENABLED=false
RAG_TOP_K=8
"""

NEW_TEMPLATE = """\
SECRET_KEY=change-me-in-production
POSTGRES_PASSWORD=zorali
CLOUD_API_KEY=
# Deep research; DuckDuckGo needs no key.
WEB_SEARCH_ENABLED=true
RAG_TOP_K=3

# Reality scan → notifications. Read-only.
REALITY_SCAN_ENABLED=true
GOAL_MAX_COST_USD=1.0
GITHUB_TOKEN=
"""


def run_sync(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), str(tmp_path / ".env"), str(tmp_path / ".env.example")],
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture
def env_dir(tmp_path: Path) -> Path:
    (tmp_path / ".env").write_text(OLD_ENV)
    (tmp_path / ".env.example").write_text(NEW_TEMPLATE)
    return tmp_path


def values(env_file: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
    return out


def test_adds_missing_keys_and_keeps_existing_values(env_dir: Path) -> None:
    result = run_sync(env_dir)
    merged = values(env_dir / ".env")

    # The three settings the release introduced arrive.
    assert merged["REALITY_SCAN_ENABLED"] == "true"
    assert merged["GOAL_MAX_COST_USD"] == "1.0"
    assert "GITHUB_TOKEN" in merged
    assert "added 3 key(s)" in result.stdout

    # Nothing the deployment had already chosen is touched — least of all secrets.
    assert merged["SECRET_KEY"] == "a-real-production-secret"
    assert merged["POSTGRES_PASSWORD"] == "not-the-default"
    assert merged["CLOUD_API_KEY"] == "sk-live-xxxx"
    assert merged["RAG_TOP_K"] == "8"


def test_comments_travel_with_the_keys_they_explain(env_dir: Path) -> None:
    run_sync(env_dir)
    text = (env_dir / ".env").read_text()
    # A bare flag nobody can interpret is not a usable migration.
    assert "# Reality scan → notifications. Read-only." in text


def test_backs_up_before_writing(env_dir: Path) -> None:
    run_sync(env_dir)
    backups = list(env_dir.glob(".env.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text() == OLD_ENV


def test_reports_differing_values_without_changing_them(env_dir: Path) -> None:
    result = run_sync(env_dir)

    # Enabling outbound web requests on a deployment that had them off is the
    # operator's call, so it is reported rather than applied.
    assert values(env_dir / ".env")["WEB_SEARCH_ENABLED"] == "false"
    assert "WEB_SEARCH_ENABLED: yours=false  template=true" in result.stdout

    # Secrets are expected to differ from the template; naming them here would
    # be noise, and printing them would leak them into logs.
    assert "SECRET_KEY" not in result.stdout
    assert "a-real-production-secret" not in result.stdout
    assert "sk-live-xxxx" not in result.stdout


def test_rerunning_changes_nothing(env_dir: Path) -> None:
    run_sync(env_dir)
    after_first = (env_dir / ".env").read_text()

    result = run_sync(env_dir)

    assert (env_dir / ".env").read_text() == after_first
    assert "nothing to add" in result.stdout
    assert len(list(env_dir.glob(".env.bak.*"))) == 1


def test_commented_out_key_still_counts_as_missing(tmp_path: Path) -> None:
    # Someone who commented a setting out is not using it; the release should
    # still deliver a live one rather than assume it is handled.
    (tmp_path / ".env").write_text("# REALITY_SCAN_ENABLED=false\nRAG_TOP_K=3\n")
    (tmp_path / ".env.example").write_text("RAG_TOP_K=3\nREALITY_SCAN_ENABLED=true\n")

    run_sync(tmp_path)

    assert values(tmp_path / ".env")["REALITY_SCAN_ENABLED"] == "true"


def test_the_shipped_template_needs_no_changes_against_itself(tmp_path: Path) -> None:
    # Guards the real .env.example: it must be a fixed point of its own merge.
    shipped = Path(__file__).resolve().parents[2] / ".env.example"
    (tmp_path / ".env").write_text(shipped.read_text())
    (tmp_path / ".env.example").write_text(shipped.read_text())

    result = run_sync(tmp_path)

    assert "nothing to add" in result.stdout
    assert "kept your value" not in result.stdout
