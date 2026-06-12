"""
Example built-in skill: Web Summarizer.
Demonstrates the skill manifest + create() pattern.
"""
from app.skills.base import BaseSkill, SkillManifest
from typing import Any

SKILL_MANIFEST = {
    "name": "web_summarizer",
    "version": "0.1.0",
    "description": "Fetch a URL and return a plain-text summary of its content",
    "author": "zorali",
    "tags": ["web", "summarize", "research"],
    "dependencies": [],
    "input_schema": {"url": "string"},
    "output_schema": {"summary": "string"},
}


class WebSummarizerSkill(BaseSkill):
    def __init__(self, manifest: SkillManifest):
        self.manifest = manifest

    async def ainvoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
        url = inputs.get("url", "")
        if not url:
            return {"summary": "No URL provided", "error": True}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, follow_redirects=True)
                text = resp.text[:3000]
            return {"summary": text, "url": url, "status": resp.status_code}
        except Exception as exc:
            return {"summary": f"Failed to fetch: {exc}", "error": True}


def create(manifest: SkillManifest) -> BaseSkill:
    return WebSummarizerSkill(manifest)
