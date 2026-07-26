"""Inbound webhook endpoint (capability map U5).

``POST /api/webhooks/github`` is the one place where something outside can
make Zorali act. It carries no JWT — GitHub cannot hold one — so the HMAC
signature *is* the authentication:

- The signature is computed over the exact raw body with the shared secret
  and compared in constant time. A body that does not verify is rejected
  before it is parsed as JSON.
- With no secret configured the endpoint refuses everything: there would be
  nothing to verify against, and an open ingest point is worse than a missing
  feature.
- ``GITHUB_REPO`` optionally pins deliveries to one repository.
- ``X-GitHub-Delivery`` makes recording idempotent, so GitHub's retries
  cannot double-trigger the routine attached to an event.
- Deliveries only ever produce event rows, a diagnosis goal and a
  notification. Nothing here writes to a repository, and no write-capable
  tool is reachable from it — the registry's ``approval_required`` gate is
  untouched.
"""
from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status

from app.core.config import settings
from app.core.rbac import admin_or_above
from app.db.repositories import repo
from app.events.github_ci import handle_ci_failure

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# Events acted on. Anything else is recorded as ignored rather than silently
# dropped, so an unexpected subscription is visible.
CI_EVENTS = {"workflow_run", "check_run", "check_suite"}
RECORDED_EVENTS = CI_EVENTS | {"push", "ping"}
# Ceiling on a delivery body; GitHub's are well under this.
MAX_BODY_BYTES = 1_000_000


def verify_signature(raw_body: bytes, signature: str | None) -> bool:
    """Constant-time check of GitHub's ``X-Hub-Signature-256`` header."""
    secret = settings.github_webhook_secret
    if not secret or not signature:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _trim_payload(event_type: str, payload: dict) -> dict:
    """The parts of a delivery worth keeping — never the whole body."""
    repository = payload.get("repository") or {}
    kept: dict = {"repository": repository.get("full_name", "")}
    if event_type == "push":
        kept.update({
            "ref": payload.get("ref", ""),
            "commits": [
                {"id": (c.get("id") or "")[:12], "message": (c.get("message") or "")[:200]}
                for c in (payload.get("commits") or [])[:10]
            ],
            "pusher": (payload.get("pusher") or {}).get("name", ""),
        })
    elif event_type == "workflow_run":
        run = payload.get("workflow_run") or {}
        kept.update({
            "name": run.get("name", ""), "conclusion": run.get("conclusion", ""),
            "status": run.get("status", ""), "head_branch": run.get("head_branch", ""),
            "run_id": run.get("id"), "html_url": run.get("html_url", ""),
        })
    elif event_type in ("check_run", "check_suite"):
        check = payload.get("check_run") or payload.get("check_suite") or {}
        kept.update({
            "name": check.get("name", ""), "conclusion": check.get("conclusion", ""),
            "status": check.get("status", ""), "html_url": check.get("html_url", ""),
        })
    return kept


def _summarize(event_type: str, action: str, payload: dict) -> str:
    repository = (payload.get("repository") or {}).get("full_name", "")
    if event_type == "push":
        count = len(payload.get("commits") or [])
        return f"push to {payload.get('ref', '')} in {repository} ({count} commit(s))"
    if event_type == "ping":
        return f"ping from {repository or 'github'}"
    trimmed = _trim_payload(event_type, payload)
    return (
        f"{event_type}.{action} — {trimmed.get('name', '')} "
        f"{trimmed.get('conclusion') or trimmed.get('status') or ''} in {repository}"
    ).strip()


def _is_ci_failure(event_type: str, payload: dict) -> bool:
    if event_type not in CI_EVENTS:
        return False
    node = payload.get("workflow_run") or payload.get("check_run") or payload.get("check_suite") or {}
    return (node.get("conclusion") or "").lower() in ("failure", "timed_out")


@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
):
    if not settings.github_webhook_secret:
        # Nothing to verify against — refuse rather than accept unsigned input.
        raise HTTPException(status_code=503, detail="Webhook endpoint is not configured")

    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    if not verify_signature(raw, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event_type = (x_github_event or "").strip()
    delivery_id = (x_github_delivery or "").strip()
    if not event_type or not delivery_id:
        raise HTTPException(status_code=400, detail="Missing GitHub event headers")

    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Malformed payload") from exc

    repo_full_name = (payload.get("repository") or {}).get("full_name", "")
    if settings.github_repo and repo_full_name and repo_full_name != settings.github_repo:
        # Signed by our secret but for a repository we do not watch.
        return {"status": "ignored", "reason": "repository not watched"}

    action = str(payload.get("action") or "")
    is_failure = _is_ci_failure(event_type, payload)
    recorded_status = (
        "received" if (event_type in RECORDED_EVENTS and (is_failure or event_type in ("push", "ping")))
        else "ignored"
    )

    event, created = await repo.record_inbound_event(
        delivery_id=delivery_id,
        event_type=event_type,
        action=action,
        repo_name=repo_full_name,
        ref=str(payload.get("ref") or _trim_payload(event_type, payload).get("head_branch") or ""),
        summary=_summarize(event_type, action, payload),
        payload=_trim_payload(event_type, payload),
        status=recorded_status,
    )
    if not created:
        # GitHub redelivery: already recorded, routine already ran.
        return {"status": "duplicate", "event_id": event["id"]}

    if is_failure:
        background_tasks.add_task(handle_ci_failure, event, payload)
        return {"status": "accepted", "event_id": event["id"], "routine": "ci_failure"}

    if recorded_status == "ignored":
        return {"status": "ignored", "event_id": event["id"], "reason": "event not actioned"}
    return {"status": "recorded", "event_id": event["id"]}


@router.get("/github/events")
async def list_events(limit: int = 50, event_type: str | None = None, _user=admin_or_above):
    """Recent inbound deliveries, newest first.

    Admin-gated: these rows describe infrastructure (repositories, branches,
    CI outcomes), not any one user's data.
    """
    return await repo.list_inbound_events(
        event_type=event_type, limit=max(1, min(limit, 200))
    )
