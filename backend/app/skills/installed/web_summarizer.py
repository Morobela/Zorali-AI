"""
Built-in skill: Web Summarizer.
Fetches a public URL and returns a plain-text summary of its content.

Security: blocks private IPs, localhost, link-local ranges, cloud metadata
endpoints, and non-HTTP schemes to prevent SSRF.
"""
import ipaddress
from urllib.parse import urlparse
from app.skills.base import BaseSkill, SkillManifest
from typing import Any

SKILL_MANIFEST = {
    "name": "web_summarizer",
    "version": "0.2.0",
    "description": "Fetch a public URL and return a plain-text summary of its content",
    "author": "zorali",
    "tags": ["web", "summarize", "research"],
    "dependencies": [],
    "input_schema": {"url": "string"},
    "output_schema": {"summary": "string"},
}

# Cloud metadata endpoints that must never be reachable
_BLOCKED_HOSTS = {
    "169.254.169.254",  # AWS/GCP/Azure metadata
    "metadata.google.internal",
    "metadata.internal",
}

_ALLOWED_SCHEMES = {"http", "https"}
_MAX_RESPONSE_BYTES = 100_000  # 100 KB
_ALLOWED_CONTENT_TYPES = {"text/", "application/json", "application/xml"}


def _is_private_address(hostname: str) -> bool:
    """Return True if the hostname resolves to a private/loopback/link-local address."""
    try:
        addr = ipaddress.ip_address(hostname)
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
    except ValueError:
        # Not a raw IP — check well-known private hostnames
        lower = hostname.lower().rstrip(".")
        if lower in ("localhost",) or lower.endswith(".local") or lower.endswith(".internal"):
            return True
        return False


def _validate_url(url: str) -> str | None:
    """Return an error string if the URL is blocked, or None if it is safe."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "Malformed URL"

    if parsed.scheme not in _ALLOWED_SCHEMES:
        return f"Scheme '{parsed.scheme}' is not allowed (only http/https)"

    host = parsed.hostname or ""
    if not host:
        return "Missing hostname"

    if host in _BLOCKED_HOSTS:
        return f"Host '{host}' is blocked"

    if _is_private_address(host):
        return f"Host '{host}' resolves to a private/internal address and is blocked"

    return None


class WebSummarizerSkill(BaseSkill):
    def __init__(self, manifest: SkillManifest):
        self.manifest = manifest

    async def ainvoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
        url = inputs.get("url", "").strip()
        if not url:
            return {"summary": "No URL provided", "error": True}

        block_reason = _validate_url(url)
        if block_reason:
            return {"summary": f"Request blocked: {block_reason}", "error": True, "blocked": True}

        try:
            import httpx

            async with httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=True,
                max_redirects=3,
                headers={"User-Agent": "Zorali/1.0 (web summarizer)"},
            ) as client:
                resp = await client.get(url)

            # Re-validate final URL after redirects
            final_url = str(resp.url)
            if final_url != url:
                block_reason = _validate_url(final_url)
                if block_reason:
                    return {"summary": f"Redirect blocked: {block_reason}", "error": True, "blocked": True}

            # Enforce content-type allowlist
            ct = resp.headers.get("content-type", "")
            if not any(ct.startswith(a) for a in _ALLOWED_CONTENT_TYPES):
                return {"summary": f"Content-type '{ct}' is not allowed", "error": True}

            text = resp.text[:_MAX_RESPONSE_BYTES]
            return {"summary": text, "url": final_url, "status": resp.status_code}

        except Exception as exc:
            return {"summary": f"Failed to fetch: {exc}", "error": True}


def create(manifest: SkillManifest) -> BaseSkill:
    return WebSummarizerSkill(manifest)
