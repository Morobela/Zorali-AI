"""Argument-level gating in the tool registry (TODO: safety gating).

Three safety stubs were deleted in the truth pass for being unwired. Two of
them described controls that already exist — untrusted framing for external
content, and per-tool role/approval gates. The third named a real gap: the
registry decided *who* was calling and *which* tool, never *what* the arguments
were, so `file_read` — `requires_role="user"` and advertised by `WS /mcp` to
every authenticated account — would read the deployment's `.env`.

These tests are the standard the deleted stubs failed: the control sits in a
path that executes, and something is shown being refused.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.core.audit import AuditEvent, audit
from app.safety.argument_guard import TOOL_RULES, check_arguments
from app.tools.registry import registry


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A workspace containing the things an operator would not want read."""
    import app.tools.file_tools as file_tools

    root = tmp_path / "workspace"
    (root / ".ssh").mkdir(parents=True)
    (root / ".env").write_text("SECRET_KEY=super-secret\n")
    (root / ".ssh" / "id_rsa").write_text("-----BEGIN PRIVATE KEY-----\n")
    (root / "server.pem").write_text("-----BEGIN CERTIFICATE-----\n")
    (root / "notes.txt").write_text("just some notes\n")
    monkeypatch.setattr(file_tools, "SAFE_ROOT", root.resolve())
    return root


async def read(path: str, role: str = "user"):
    return await registry.execute(
        "file_read", {"path": str(path)}, actor="alice", actor_role=role, caller="alice"
    )


# ── the leak this closes ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_plain_user_cannot_read_the_deployments_env(workspace) -> None:
    with pytest.raises(PermissionError, match="holds credentials"):
        await read(workspace / ".env")


@pytest.mark.asyncio
async def test_an_owner_cannot_either(workspace) -> None:
    """Not role-exempt on purpose.

    An owner's session is the one a prompt injection would most like to borrow,
    and nobody chatting with an assistant means for it to read their private
    key out loud.
    """
    with pytest.raises(PermissionError, match="holds credentials"):
        await read(workspace / ".env", role="owner")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [".env", ".ssh/id_rsa", "server.pem"])
async def test_the_obvious_credential_shapes_are_refused(workspace, name: str) -> None:
    with pytest.raises(PermissionError):
        await read(workspace / name)


@pytest.mark.asyncio
async def test_an_ordinary_file_still_reads(workspace) -> None:
    """A gate that blocks the work it guards gets removed."""
    assert await read(workspace / "notes.txt") == "just some notes\n"


# ── the ways around it ───────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("spelling", ["./.env", "sub/../.env"])
async def test_a_differently_spelled_path_is_the_same_file(workspace, spelling: str) -> None:
    with pytest.raises(PermissionError, match="holds credentials"):
        await read(f"{workspace}/{spelling}")


@pytest.mark.asyncio
async def test_a_symlink_does_not_launder_a_secret(workspace) -> None:
    """The bypass a lexical-only check would have shipped with.

    `ln -s .env innocent.txt` is one line, so the guard resolves as well as
    normalising.
    """
    (workspace / "innocent.txt").symlink_to(workspace / ".env")

    with pytest.raises(PermissionError, match="holds credentials"):
        await read(workspace / "innocent.txt")


@pytest.mark.asyncio
async def test_a_symlink_into_a_credential_directory_is_refused(workspace) -> None:
    (workspace / "deep.txt").symlink_to(workspace / ".ssh" / "id_rsa")

    with pytest.raises(PermissionError):
        await read(workspace / "deep.txt")


@pytest.mark.asyncio
async def test_an_unresolvable_path_is_refused_rather_than_read(workspace) -> None:
    # Not being able to tell what a name points at is not a reason to read it.
    (workspace / "loop_a").symlink_to(workspace / "loop_b")
    (workspace / "loop_b").symlink_to(workspace / "loop_a")

    with pytest.raises(PermissionError, match="could not be resolved"):
        await read(workspace / "loop_a")


# ── it is enforced where it counts ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_refusal_is_audited(workspace, monkeypatch) -> None:
    records = []
    monkeypatch.setattr(audit, "record", lambda event, **kw: records.append((event, kw)))

    with pytest.raises(PermissionError):
        await read(workspace / ".env")

    blocked = [kw for event, kw in records if event is AuditEvent.TOOL_BLOCKED]
    assert blocked, f"no TOOL_BLOCKED record in {records!r}"
    assert blocked[0]["outcome"] == "argument_denied"
    assert "credentials" in blocked[0]["reason"]


def test_the_guard_runs_inside_registry_execute() -> None:
    """The failure mode of the deleted stubs, asserted directly.

    They were plausible modules nothing called. If this check is ever the only
    thing left of the guard, it should fail loudly.
    """
    source = inspect.getsource(registry.execute)

    assert "check_arguments" in source, "the guard is not called on the execution path"


def test_every_path_taking_tool_declares_a_policy() -> None:
    """A new tool that takes a path must say what it will accept.

    No entry in TOOL_RULES means no argument policy — which is a decision, so
    it should be made deliberately rather than by forgetting.
    """
    path_tools = {
        spec.name for spec in registry.get_tools()
        if "path" in spec.input_schema
    }
    undeclared = path_tools - set(TOOL_RULES)

    assert not undeclared, (
        f"{sorted(undeclared)} take a path but declare no rule in "
        "safety/argument_guard.TOOL_RULES."
    )


# ── the checker itself ───────────────────────────────────────────────────────

def test_a_tool_with_no_rules_is_left_alone() -> None:
    assert check_arguments("calculator", {"expression": "2+2"}) is None


def test_a_non_string_argument_is_not_inspected() -> None:
    # Schema validation is a different job; the guard must not crash on input
    # that never reaches the handler anyway.
    assert check_arguments("file_read", {"path": 42}) is None


def test_a_missing_argument_is_not_inspected() -> None:
    assert check_arguments("file_read", {}) is None


def test_a_nonexistent_path_is_still_judged(tmp_path: Path) -> None:
    # Matters for file_write, whose target does not exist yet.
    assert check_arguments("file_write", {"path": str(tmp_path / ".env")})
    assert check_arguments("file_write", {"path": str(tmp_path / "notes.txt")}) is None
