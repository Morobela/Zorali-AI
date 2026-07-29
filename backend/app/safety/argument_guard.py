"""Argument-level gating for tool execution.

The registry decides *who* is calling and *which* tool. It has never looked at
*what* the arguments are, and the gap that opened is concrete: `file_read` is
`requires_role="user"` and `WS /mcp` advertises every registered tool, so any
authenticated account could call

    tools/call file_read {"path": "/workspace/.env"}

and read the deployment's secrets. `file_tools._safe` keeps the path inside
`/workspace`; nothing said the file itself was off limits.

This is the third of the deleted safety stubs — `command_guard` — reintroduced
where it holds. The other two were not reintroduced, because the controls they
described already exist and a second copy would only look like more security:

- `prompt_integrity` (untrusted framing for external content) is implemented in
  `api/chat.py` and `agents/chat_tools.py`, which fence retrieved files, web
  pages and tool output as UNTRUSTED evidence.
- `action_classifier` (per-action safety class and approval) is implemented as
  `ToolSpec.requires_role` and `ToolSpec.approval_required`, enforced in
  `registry.execute` with an audit record on every decision.

**What this is not.** A denylist of names is a floor, not a boundary. It stops
an agent reaching the obvious high-value files; it cannot stop an operator who
puts a secret in `/workspace/notes.txt`. It is worth having because the pathway
it closes is one a *user* can drive without ever touching the host — including
through a prompt injection aimed at somebody else's session, which is why the
rule holds for every role including `owner`. Nobody chatting with an assistant
intends to have it read their private key out loud.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

# Files whose whole purpose is to hold a credential.
SECRET_FILENAMES = frozenset({
    ".env", ".env.local", ".env.production", ".env.development",
    ".netrc", ".pgpass", ".git-credentials", ".npmrc", ".pypirc",
    ".htpasswd", ".dockercfg", "credentials", "secrets.json",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
})

# Extensions that carry key material.
SECRET_SUFFIXES = frozenset({
    ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".ppk", ".asc", ".gpg",
})

# Directories that exist to hold credentials — anything inside one is refused.
SECRET_DIRECTORIES = frozenset({
    ".ssh", ".aws", ".gnupg", ".gpg", ".docker", ".kube", ".azure", ".config/gcloud",
})


@dataclass(frozen=True)
class GuardRule:
    """One argument of one tool, and the check that applies to it."""

    field: str
    kind: str  # currently only "secret_path"


# Declared per tool. A tool with no entry has no argument policy — which is a
# statement, so adding a tool that takes a path means adding it here too
# (`test_argument_guard` fails if a path-taking tool is left undeclared).
TOOL_RULES: dict[str, tuple[GuardRule, ...]] = {
    "file_read": (GuardRule("path", "secret_path"),),
    "file_write": (GuardRule("path", "secret_path"),),
}


def _lexical_parts(raw_path: str) -> list[str]:
    """Path components with `.` dropped and `..` collapsed, without touching disk."""
    parts: list[str] = []
    for part in PurePosixPath(raw_path).parts:
        if part == ".":
            continue
        if part == ".." and parts and parts[-1] not in ("..", "/"):
            parts.pop()
            continue
        parts.append(part)
    return parts


def _secret_reason(parts: list[str]) -> str | None:
    """Why these path components name a credential, or None."""
    if not parts:
        return None
    name = parts[-1]
    lowered = name.lower()

    if lowered in SECRET_FILENAMES:
        return f"{name} holds credentials"
    if PurePosixPath(lowered).suffix in SECRET_SUFFIXES:
        return f"{name} looks like key material"
    for part in parts[:-1]:
        if part.lower() in SECRET_DIRECTORIES:
            return f"{part} holds credentials"
    return None


def _looks_like_a_secret(raw_path: str) -> str | None:
    """Reason this path is off limits, or None.

    Checked twice, because either check alone has a hole:

    - **Lexically**, so `/workspace/./.env` and `/workspace/sub/../.env` are the
      same file as `/workspace/.env`, and so a path that does not exist yet
      (a `file_write` target) is still judged.
    - **Resolved**, because a lexical check is one `ln -s innocent.txt .env`
      away from useless. This follows symlinks, which is the whole point.

    A path that cannot be resolved at all — a symlink loop — is refused rather
    than allowed: not being able to tell what a name points at is not a reason
    to read it.
    """
    if not raw_path:
        return None

    reason = _secret_reason(_lexical_parts(raw_path))
    if reason:
        return reason

    try:
        resolved = Path(raw_path).resolve()
    except (OSError, RuntimeError) as exc:
        # pathlib raises RuntimeError, not OSError, on a symlink loop.
        return f"path could not be resolved ({type(exc).__name__})"
    return _secret_reason(list(resolved.parts))


def check_arguments(tool_name: str, inputs: Mapping[str, object]) -> str | None:
    """Why this call must not run, or None to allow it.

    Pure and synchronous on purpose: it is called on every tool execution, and
    a gate that can hang is a gate that gets removed.
    """
    for rule in TOOL_RULES.get(tool_name, ()):
        value = inputs.get(rule.field)
        if not isinstance(value, str):
            continue
        if rule.kind == "secret_path":
            reason = _looks_like_a_secret(value)
            if reason:
                return f"refusing to touch {rule.field}={value!r} — {reason}"
    return None
