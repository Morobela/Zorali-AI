"""Explicit caller context for data-access functions.

Every repository / retrieval function takes a required ``owner_id`` that is
either the authenticated user's id (JWT ``sub``) or the explicit ``SYSTEM``
marker for internal callers (background ingestion, maintenance scripts).
There is no implicit trusted mode: passing ``None`` — e.g. a missing ``sub``
claim — raises ``TypeError`` instead of silently disabling ownership checks.
"""
from __future__ import annotations


class _SystemCaller:
    """Singleton marker for trusted internal callers (use the SYSTEM constant)."""

    __slots__ = ()
    _instance: "_SystemCaller | None" = None

    def __new__(cls) -> "_SystemCaller":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "SYSTEM"


SYSTEM = _SystemCaller()

# A caller is an authenticated user id or the explicit SYSTEM marker.
Caller = str | _SystemCaller


def resolve_owner_filter(owner_id: Caller) -> str | None:
    """Validate a caller and translate it into an ownership filter.

    Returns ``None`` for ``SYSTEM`` (no ownership filter) and the user id for
    a real user. Anything else — most importantly ``None`` from a missing JWT
    ``sub`` — is rejected so an unscoped query can never happen by accident.
    """
    if owner_id is SYSTEM:
        return None
    if isinstance(owner_id, str) and owner_id:
        return owner_id
    raise TypeError(
        "owner_id must be an authenticated user id or the explicit SYSTEM "
        f"marker, got {owner_id!r}"
    )
