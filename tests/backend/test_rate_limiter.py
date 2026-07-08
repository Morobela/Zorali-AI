"""Rate limiter behavior: per-sub buckets with IP fallback, refill, isolation."""
import asyncio
import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.auth import create_access_token
from app.core.rate_limiter import RateLimiter


def _request(headers: dict | None = None, client_ip: str = "10.0.0.1") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/x",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": (client_ip, 12345),
    }
    return Request(scope)


def _bearer(sub: str, role: str = "user") -> dict:
    return {"Authorization": f"Bearer {create_access_token(sub, role)}"}


def test_key_is_jwt_sub_not_token_string():
    """Two different tokens for the same sub must share one bucket — minting a
    fresh token must not reset a user's rate limit."""
    limiter = RateLimiter(capacity=60, refill_rate=1)
    k1 = limiter._client_key(_request(_bearer("alice")))
    time.sleep(1.1)  # different iat/exp → different token string
    k2 = limiter._client_key(_request(_bearer("alice")))
    assert k1 == k2 == "sub:alice"


def test_different_subs_get_isolated_buckets():
    limiter = RateLimiter(capacity=1, refill_rate=0.0001)
    asyncio.run(limiter.check(_request(_bearer("alice"))))
    # alice's bucket is empty now…
    with pytest.raises(HTTPException) as exc:
        asyncio.run(limiter.check(_request(_bearer("alice"))))
    assert exc.value.status_code == 429
    # …but bob is unaffected.
    asyncio.run(limiter.check(_request(_bearer("bob"))))


def test_unauthenticated_requests_fall_back_to_ip():
    limiter = RateLimiter(capacity=60, refill_rate=1)
    assert limiter._client_key(_request(client_ip="203.0.113.9")) == "ip:203.0.113.9"
    # X-Forwarded-For (first hop) wins over the socket peer.
    key = limiter._client_key(
        _request({"X-Forwarded-For": "198.51.100.7, 10.0.0.2"}, client_ip="10.0.0.99")
    )
    assert key == "ip:198.51.100.7"


def test_ip_buckets_isolated_from_each_other_and_from_subs():
    limiter = RateLimiter(capacity=1, refill_rate=0.0001)
    asyncio.run(limiter.check(_request(client_ip="203.0.113.1")))
    with pytest.raises(HTTPException):
        asyncio.run(limiter.check(_request(client_ip="203.0.113.1")))
    asyncio.run(limiter.check(_request(client_ip="203.0.113.2")))  # other IP fine
    asyncio.run(limiter.check(_request(_bearer("carol"))))         # sub bucket fine


def test_garbage_token_still_gets_a_bucket():
    limiter = RateLimiter(capacity=60, refill_rate=1)
    key = limiter._client_key(_request({"Authorization": "Bearer not.a.jwt"}))
    assert key.startswith("jwt:")


def test_bucket_refills_over_time():
    limiter = RateLimiter(capacity=1, refill_rate=50)  # 50 tokens/second
    asyncio.run(limiter.check(_request(_bearer("dave"))))
    with pytest.raises(HTTPException):
        asyncio.run(limiter.check(_request(_bearer("dave"))))
    time.sleep(0.1)  # ≥1 token refilled
    asyncio.run(limiter.check(_request(_bearer("dave"))))
