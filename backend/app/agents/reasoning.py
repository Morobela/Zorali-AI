"""Reasoning-model output handling.

Models like deepseek-r1 and qwen3 (via Ollama) emit their chain of thought
inside ``<think>…</think>`` before the answer. The UI buffers that into a
collapsible "Thinking" block; the backend strips it so it never enters the
stored assistant message (and therefore never TTS, history, or later
prompts).
"""
from __future__ import annotations

import re

_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)
# A <think> that never closed (stream stopped mid-thought): drop to the end.
_OPEN_THINK_RE = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)


def split_think(text: str) -> tuple[str, str]:
    """Split model output into ``(thinking, answer)``.

    Handles multiple ``<think>`` blocks (concatenated, newline-joined) and an
    unclosed trailing block. Text without think tags comes back unchanged as
    the answer with empty thinking.
    """
    if "<think>" not in text.lower():
        return "", text
    thinking_parts = [m.group(1).strip() for m in _THINK_RE.finditer(text)]
    answer = _THINK_RE.sub("", text)
    open_match = _OPEN_THINK_RE.search(answer)
    if open_match:
        thinking_parts.append(re.sub(r"(?i)^<think>", "", open_match.group(0)).strip())
        answer = answer[: open_match.start()]
    return "\n".join(part for part in thinking_parts if part), answer.strip()


def strip_think(text: str) -> str:
    """The answer with all thinking removed (what gets persisted/spoken)."""
    return split_think(text)[1]
