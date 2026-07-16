"""Context-window budgeting: token estimation and history splitting.

Token counts use the cheap ``chars / 4`` approximation — for English prose a
token averages ~4 characters, so the estimate is within ~±25% of real
tokenizer counts, which is plenty for deciding when a conversation no longer
fits the model's window. No tokenizer dependency, no model-specific tables.
"""
from __future__ import annotations

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Cheap token estimate for ``text`` (chars/4, minimum 1 for non-empty)."""
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def estimate_history_tokens(messages: list[dict]) -> int:
    """Estimated tokens for a list of chat messages (content only — the few
    tokens of role/formatting overhead are noise at this precision)."""
    return sum(estimate_tokens(m.get("content", "")) for m in messages)


def split_history_for_budget(
    history: list[dict],
    *,
    max_tokens: int,
    keep_messages: int,
) -> tuple[list[dict], list[dict]]:
    """Split ``history`` into ``(older, recent)`` when it exceeds the budget.

    Within budget → ``([], history)`` (short histories stay untouched). Over
    budget → the trailing ``keep_messages`` messages stay verbatim and
    everything before them becomes the ``older`` slice to be summarized.
    """
    if estimate_history_tokens(history) <= max_tokens:
        return [], history
    if len(history) <= keep_messages:
        return [], history
    return history[:-keep_messages], history[-keep_messages:]
