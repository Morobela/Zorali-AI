"""Image attachments for vision-capable chat models.

The WebSocket payload carries ``attachments: [{"type": "image", "name": ...,
"data": "<base64 or data: URL>"}]``. These helpers validate/bound the images
and attach them to the final user message in the Ollama message format
(``{"role": "user", "content": ..., "images": [<base64>, ...]}``), which
llava / qwen-vl / llama3.2-vision models consume directly. The cloud provider
translates that same field into OpenAI content parts (see cloud_provider).
"""
from __future__ import annotations

import base64
import binascii

MAX_IMAGES = 4
MAX_IMAGE_B64_CHARS = 8_000_000  # ~6 MB decoded per image


def extract_image_attachments(attachments: list | None) -> list[str]:
    """Pull validated base64 image payloads out of a WS attachments list.

    Accepts raw base64 or ``data:image/...;base64,...`` URLs (the frontend
    sends FileReader data URLs). Anything malformed, oversized, or beyond
    MAX_IMAGES is dropped silently — a bad attachment should not kill the
    chat turn.
    """
    images: list[str] = []
    for att in attachments or []:
        if not isinstance(att, dict) or att.get("type") != "image":
            continue
        data = att.get("data")
        if not isinstance(data, str) or not data:
            continue
        if data.startswith("data:"):
            _, _, data = data.partition(",")
        data = data.strip()
        if not data or len(data) > MAX_IMAGE_B64_CHARS:
            continue
        try:
            base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            continue
        images.append(data)
        if len(images) >= MAX_IMAGES:
            break
    return images


def attach_images(messages: list[dict], images: list[str]) -> list[dict]:
    """Return a copy of ``messages`` with ``images`` on the last user message.

    Only the live turn carries pixels — persisted history stays text-only.
    No user message (shouldn't happen) → messages returned unchanged.
    """
    if not images:
        return messages
    out = [dict(m) for m in messages]
    for msg in reversed(out):
        if msg.get("role") == "user":
            msg["images"] = images
            break
    return out
