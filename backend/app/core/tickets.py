"""Single-use WebSocket authentication tickets.

JWTs must never travel in a WebSocket URL: query strings end up in proxy and
server access logs. Instead, an authenticated client POSTs /api/ws-ticket,
receives a random single-use ticket bound to its user id, and presents that
when opening the socket. Tickets live in Redis with a short TTL and are
deleted atomically on redemption, so a logged ticket is worthless: it has
either been consumed already or expires within a minute.
"""
from __future__ import annotations

import asyncio
import json
import secrets

from redis.asyncio import Redis

from app.core.config import settings

TICKET_TTL_SECONDS = 60
_PREFIX = "ws_ticket:"

_client: Redis | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


def _redis() -> Redis:
    """Redis client cached per event loop.

    The connection pool binds to the loop it was created on; under test
    runners every request may run on a fresh loop, so reusing a client across
    loops would fail. In production (one uvicorn loop) this caches normally.
    """
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is None or _client_loop is not loop:
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
        _client_loop = loop
    return _client


async def issue_ticket(user: dict) -> str:
    """Create a ticket bound to the authenticated user. Raises on Redis failure."""
    ticket = secrets.token_urlsafe(32)
    payload = json.dumps({"sub": user["sub"], "role": user.get("role", "readonly")})
    await _redis().set(_PREFIX + ticket, payload, ex=TICKET_TTL_SECONDS)
    return ticket


async def redeem_ticket(ticket: str | None) -> dict | None:
    """Atomically consume a ticket and return its {sub, role} binding.

    Returns ``None`` for a missing, expired, already-used or malformed ticket,
    and also when Redis is unreachable — the WebSocket handshake then fails
    closed instead of falling back to weaker auth.
    """
    if not ticket:
        return None
    try:
        payload = await _redis().getdel(_PREFIX + ticket)
    except Exception:
        return None
    if not payload:
        return None
    try:
        user = json.loads(payload)
    except ValueError:
        return None
    return user if isinstance(user, dict) and user.get("sub") else None


async def close_ticket_store() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
