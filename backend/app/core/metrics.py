"""Prometheus metrics: HTTP request counter + latency histogram.

Wired as an outer HTTP middleware in app.main so it measures every request
(including rate-limited rejections). Paths are labelled by their route
*template* (e.g. ``/api/files/{file_id}/status``) rather than the concrete
URL, so per-id requests don't explode label cardinality.
"""
from __future__ import annotations

import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response

REQUEST_COUNT = Counter(
    "zorali_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

REQUEST_LATENCY = Histogram(
    "zorali_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or request.url.path


async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    status_code = 500  # default if call_next raises before producing a response
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed = time.perf_counter() - start
        path = _route_template(request)
        REQUEST_COUNT.labels(request.method, path, str(status_code)).inc()
        REQUEST_LATENCY.labels(request.method, path).observe(elapsed)


def metrics_endpoint() -> Response:
    """Render the current metrics in Prometheus text exposition format."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
