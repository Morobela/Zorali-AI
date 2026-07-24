"""Async service health probes.

TCP connect probes for Postgres and Redis, HTTP GET probes for Ollama and
the frontend. Every probe returns ``status`` ("up"/"down") plus the observed
latency in milliseconds, so snapshots can track degradation as well as
availability. Targets default to the services named in config.
"""
from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse

import httpx

from app.core.config import settings

PROBE_TIMEOUT_S = 2.0


def default_targets() -> dict[str, dict]:
    """The services named in config, each as a {"kind", ...} probe spec."""
    redis = urlparse(settings.redis_url)
    return {
        "ollama": {"kind": "http", "url": settings.ollama_host.rstrip("/") + "/api/tags"},
        "postgres": {"kind": "tcp", "host": settings.postgres_host, "port": settings.postgres_port},
        "redis": {"kind": "tcp", "host": redis.hostname or "localhost", "port": redis.port or 6379},
        "frontend": {"kind": "http", "url": settings.frontend_url},
    }


async def _probe_tcp(host: str, port: int) -> dict:
    start = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=PROBE_TIMEOUT_S)
        latency_ms = (time.perf_counter() - start) * 1000
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return {"status": "up", "latency_ms": round(latency_ms, 1)}
    except Exception as exc:
        return {"status": "down", "latency_ms": None, "detail": type(exc).__name__}


async def _probe_http(url: str) -> dict:
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
            resp = await client.get(url)
        latency_ms = (time.perf_counter() - start) * 1000
        # Any HTTP response below 500 means the service is listening and
        # answering; 5xx counts as down-for-purpose with the code as detail.
        status = "up" if resp.status_code < 500 else "down"
        return {"status": status, "latency_ms": round(latency_ms, 1), "detail": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"status": "down", "latency_ms": None, "detail": type(exc).__name__}


async def check_services(targets: dict[str, dict] | None = None) -> dict[str, dict]:
    """Probe all targets concurrently → {name: {"status", "latency_ms", ...}}."""
    targets = default_targets() if targets is None else targets

    async def _probe(spec: dict) -> dict:
        if spec["kind"] == "tcp":
            return await _probe_tcp(spec["host"], spec["port"])
        return await _probe_http(spec["url"])

    names = list(targets)
    results = await asyncio.gather(*(_probe(targets[n]) for n in names))
    return dict(zip(names, results))
