"""Nightly self-check (capability map U8, phase one).

Runs the three checks the map names — the test suite, ruff, and a checker
that verifies FEATURE_PARITY.md claims against the codebase — records the
result, files a GitHub issue per finding, and notifies the admins.

What it deliberately does not do: change any code. Phase one reports; a human
reads the issue and decides. Phase two (proposing patches as branches gated
on CI) is not implemented, and merge authority is never automated — see
``github_issues`` for where that invariant lives.

Everything degrades: with no token the findings are still recorded and
notified, just not filed; a checker that cannot run becomes a finding of its
own rather than an exception.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.db.repositories import repo
from app.selfcheck import github_issues
from app.selfcheck.parity_checker import app_routes, check_parity_doc, settings_names

_log = logging.getLogger(__name__)

# The repo root: .../backend/app/selfcheck/runner.py → up three.
REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_DOC = REPO_ROOT / "docs" / "FEATURE_PARITY.md"

_LINT_TIMEOUT_S = 180.0
_TEST_TIMEOUT_S = 1800.0
# How much command output is kept in a finding.
_OUTPUT_CHARS = 4000


@dataclass
class Finding:
    kind: str      # "parity" | "lint" | "tests"
    key: str       # stable identity for issue dedupe
    title: str
    detail: str

    def as_dict(self) -> dict:
        return {"kind": self.kind, "key": self.key, "title": self.title, "detail": self.detail}


async def _run_command(args: list[str], *, timeout: float) -> tuple[int, str]:
    """Run a checker process; returns (exit code, combined output)."""
    if shutil.which(args[0]) is None:
        return 127, f"{args[0]} is not installed"
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=str(REPO_ROOT),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, f"timed out after {timeout:.0f}s"
    return proc.returncode or 0, out.decode(errors="replace")


async def check_lint() -> list[Finding]:
    code, output = await _run_command(
        ["ruff", "check", "backend/app", "tests/backend", "infra/scripts"],
        timeout=_LINT_TIMEOUT_S,
    )
    if code == 0:
        return []
    return [Finding(
        kind="lint", key="lint:ruff",
        title="Nightly self-check: ruff reports lint errors",
        detail=output[-_OUTPUT_CHARS:],
    )]


async def check_tests() -> list[Finding]:
    code, output = await _run_command(
        ["python3", "-m", "pytest", "tests/backend", "-q", "--no-header"],
        timeout=_TEST_TIMEOUT_S,
    )
    if code == 0:
        return []
    return [Finding(
        kind="tests", key="tests:backend",
        title="Nightly self-check: the backend suite is failing",
        detail=output[-_OUTPUT_CHARS:],
    )]


def check_parity(doc_path: Path | None = None) -> list[Finding]:
    """Claims in the parity doc that the codebase does not support."""
    findings = check_parity_doc(
        doc_path or PARITY_DOC,
        repo_root=REPO_ROOT,
        routes=app_routes(),
        setting_names=settings_names(),
    )
    return [
        Finding(
            kind="parity", key=f.key,
            title=f"Nightly self-check: FEATURE_PARITY.md overclaims '{f.feature}'",
            detail=(
                f"{f.detail}\n\n"
                "Either implement the claim or correct the row. This issue was filed "
                "automatically by Zorali's nightly self-check; nothing was changed."
            ),
        )
        for f in findings
    ]


async def run_self_check(*, run_tests: bool = True, doc_path: Path | None = None) -> dict:
    """One full self-check pass. Never raises: a failure is recorded, not thrown."""
    record = await repo.create_self_check()
    findings: list[Finding] = []
    error = ""
    try:
        findings.extend(check_parity(doc_path))
        findings.extend(await check_lint())
        if run_tests:
            findings.extend(await check_tests())
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        _log.warning("Self-check aborted: %s", error)

    filed: list[dict] = []
    for finding in findings:
        try:
            number, created = await github_issues.file_once(
                finding.title, finding.detail, finding.key
            )
        except Exception:
            number, created = None, False
        filed.append({"key": finding.key, "issue": number, "created": created})

    created_count = sum(1 for f in filed if f["created"] and f["issue"])
    final = await repo.finish_self_check(
        record["id"],
        status="failed" if error else ("findings" if findings else "clean"),
        findings=[f.as_dict() for f in findings],
        issues_filed=created_count,
        error=error,
    )
    await _notify(findings, created_count)
    return final or {}


async def _notify(findings: list[Finding], issues_filed: int) -> None:
    """Tell the admins what the night's run found. Silence when clean."""
    if not findings:
        return
    try:
        recipients = await repo.list_admin_user_ids()
        by_kind: dict[str, int] = {}
        for finding in findings:
            by_kind[finding.kind] = by_kind.get(finding.kind, 0) + 1
        summary = ", ".join(f"{count} {kind}" for kind, count in sorted(by_kind.items()))
        body_lines = [f"{len(findings)} finding(s): {summary}."]
        if issues_filed:
            body_lines.append(f"{issues_filed} new issue(s) filed.")
        elif not github_issues.can_file():
            body_lines.append("No GitHub token configured — nothing was filed.")
        else:
            body_lines.append("No new issues filed (already open).")
        body_lines.append("")
        body_lines.extend(f"• {f.title}" for f in findings[:10])
        for user_id in recipients:
            await repo.create_notification(
                user_id, "self_check",
                f"Nightly self-check: {len(findings)} finding(s)",
                body="\n".join(body_lines),
            )
    except Exception:
        return


def seconds_until_next_run(now_epoch: float, hour_utc: int) -> float:
    """Seconds from ``now`` until the next occurrence of ``hour_utc``."""
    from datetime import datetime, timedelta, timezone

    now = datetime.fromtimestamp(now_epoch, tz=timezone.utc)
    target = now.replace(hour=hour_utc % 24, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()
