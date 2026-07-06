"""Phase 5 coverage: /metrics endpoint, settings-driven rate limiter,
and pypdf-based PDF extraction."""
import io

from fastapi.testclient import TestClient

from app.main import app
from app.api.files import extract_text

client = TestClient(app)

_MINIMAL_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 68>>stream
BT /F1 24 Tf 100 700 Td (Hello Zorali PDF extraction works) Tj ET
endstream endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f
trailer<</Root 1 0 R/Size 6>>
startxref
0
%%EOF"""


def test_metrics_endpoint_exposes_request_metrics():
    # Generate at least one request to record.
    client.get("/api/health")
    res = client.get("/metrics")
    assert res.status_code == 200
    body = res.text
    assert "zorali_http_requests_total" in body
    assert "zorali_http_request_duration_seconds" in body


def test_rate_limiter_reads_settings():
    from app.core.rate_limiter import limiter
    from app.core.config import settings

    assert limiter._capacity == settings.rate_limit_capacity
    assert limiter._refill_rate == settings.rate_limit_refill


def test_rate_limiter_returns_429_response_not_500():
    """When the bucket is empty the middleware must produce a real 429 response.

    HTTPException raised inside middleware bypasses FastAPI's handlers, so the
    limiter converts it to a JSONResponse itself.
    """
    import asyncio
    from starlette.requests import Request
    from app.core.rate_limiter import RateLimiter

    limiter = RateLimiter(capacity=1.0, refill_rate=0.0001)
    scope = {"type": "http", "method": "GET", "path": "/x", "headers": [], "client": ("1.2.3.4", 1)}
    request = Request(scope)

    async def call_next(_):
        from starlette.responses import PlainTextResponse
        return PlainTextResponse("ok")

    async def run():
        first = await limiter(request, call_next)
        second = await limiter(request, call_next)
        return first, second

    first, second = asyncio.run(run())
    assert first.status_code == 200
    assert second.status_code == 429
    assert "retry-after" in {k.decode().lower() for k, _ in second.raw_headers}


def test_extract_text_pdf_uses_pypdf():
    text = extract_text("doc.pdf", _MINIMAL_PDF)
    assert "Hello Zorali PDF extraction works" in text


def test_extract_text_pdf_fallback_on_garbage():
    # Non-PDF bytes with a .pdf name must fall back to the failure message,
    # never raise.
    text = extract_text("broken.pdf", b"this is not really a pdf at all")
    assert text.startswith("[PDF uploaded")


def test_extract_text_plaintext_still_works():
    assert extract_text("notes.txt", b"alpha beta gamma") == "alpha beta gamma"
