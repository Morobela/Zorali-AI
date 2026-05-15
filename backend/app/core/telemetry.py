import logging

logger = logging.getLogger("zorali.telemetry")


def setup_telemetry(app):
    return app


def track_event(event: str, **payload):
    safe_payload = {k: ("***" if "key" in k.lower() or "secret" in k.lower() else v) for k, v in payload.items()}
    logger.info("event=%s payload=%s", event, safe_payload)
