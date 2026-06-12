"""
Token-bucket rate limiter middleware.
Security priority: prevents abuse before any compute runs.
"""
from __future__ import annotations
import time
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from fastapi import Request, HTTPException, status


@dataclass
class _Bucket:
    capacity: float
    refill_rate: float  # tokens per second
    tokens: float = field(init=False)
    last_refill: float = field(init=False)

    def __post_init__(self):
        self.tokens = self.capacity
        self.last_refill = time.monotonic()

    def consume(self, amount: float = 1.0) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False


class RateLimiter:
    """
    Per-client token-bucket limiter.
    Identifies clients by JWT sub (preferred) → IP fallback.
    """

    def __init__(self, capacity: float = 60.0, refill_rate: float = 1.0):
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._buckets: dict[str, _Bucket] = defaultdict(
            lambda: _Bucket(self._capacity, self._refill_rate)
        )
        self._lock = asyncio.Lock()

    def _client_key(self, request: Request) -> str:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            # Use first 16 chars of token as cheap key (not full decode for performance)
            return f"jwt:{auth[7:23]}"
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
        if request.client:
            return f"ip:{request.client.host}"
        return "ip:unknown"

    async def check(self, request: Request, cost: float = 1.0) -> None:
        key = self._client_key(request)
        async with self._lock:
            allowed = self._buckets[key].consume(cost)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please slow down.",
                headers={"Retry-After": str(int(1.0 / self._refill_rate))},
            )

    async def __call__(self, request: Request, call_next):
        await self.check(request)
        return await call_next(request)


limiter = RateLimiter(capacity=60.0, refill_rate=1.0)
