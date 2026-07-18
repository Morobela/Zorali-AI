"""Rolling conversation summarization for context-window management.

When a session's history exceeds ``CONTEXT_MAX_TOKENS`` (chars/4 estimate,
see ``context_pruner``), the turns older than the verbatim window are folded
into one summary by a single non-streamed LLM call. The summary persists in
the owner-scoped ``session_summaries`` table so later turns reuse it instead
of recomputing; it is only refreshed when enough new uncovered turns pile up
(a quarter of the budget). The summarizer only ever sees the session's own
messages — history is loaded through the owner-scoped repository, so another
user's data can never leak into a summary.
"""
from __future__ import annotations

from app.core.caller import Caller
from app.core.config import settings
from app.memory.context_pruner import estimate_history_tokens, split_history_for_budget
from app.models.llm import stream_llm

# A summary should be a compact digest, never a second transcript.
_MAX_SUMMARY_CHARS = 2400
# How much of each older message the summarizer gets to read.
_MAX_MESSAGE_CHARS = 1200

_SUMMARIZE_PROMPT = (
    "You maintain a rolling summary of a conversation between a user and an "
    "assistant. Merge the previous summary (if any) with the new turns into "
    "ONE compact summary of at most 250 words. Keep: user goals and "
    "preferences, decisions made, facts established, open questions, and "
    "anything the assistant promised. Drop pleasantries and repetition. "
    "Reply with the summary text only."
)


class RollingSummarizer:
    async def summarize(
        self,
        previous_summary: str,
        new_messages: list[dict],
        *,
        model: str | None = None,
        local_first: bool = True,
    ) -> str:
        """One non-streamed LLM call merging ``previous_summary`` with
        ``new_messages`` into an updated summary."""
        transcript = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')[:_MAX_MESSAGE_CHARS]}"
            for m in new_messages
        )
        parts = []
        if previous_summary:
            parts.append(f"Previous summary:\n{previous_summary}")
        parts.append(f"New conversation turns:\n{transcript}")
        messages = [
            {"role": "system", "content": _SUMMARIZE_PROMPT},
            {"role": "user", "content": "\n\n".join(parts)},
        ]
        chunks: list[str] = []
        async for token in stream_llm(messages, model=model, local_first=local_first):
            chunks.append(token)
        return "".join(chunks).strip()[:_MAX_SUMMARY_CHARS]

    async def condense_history(
        self,
        project_id: str,
        session_id: str,
        history: list[dict],
        *,
        owner_id: Caller,
        model: str | None = None,
        local_first: bool = True,
    ) -> tuple[list[dict], str | None]:
        """Fit ``history`` into the context budget.

        Returns ``(messages_to_send, summary_or_none)``. Within budget the
        history comes back untouched with no summary (and no DB access).
        Over budget, the trailing ``CONTEXT_KEEP_MESSAGES`` stay verbatim and
        older turns are covered by the rolling summary — reused from the
        ``session_summaries`` row when it is fresh enough, refreshed with one
        LLM call when the uncovered backlog exceeds a quarter of the budget.
        Older messages not yet folded into a reused summary are kept verbatim
        so nothing silently drops out of context.
        """
        older, recent = split_history_for_budget(
            history,
            max_tokens=settings.context_max_tokens,
            keep_messages=settings.context_keep_messages,
        )
        if not older:
            return history, None

        from app.db.repositories import repo

        stored = await repo.get_session_summary(project_id, session_id, owner_id=owner_id)
        covered = min(stored["covered_messages"], len(older)) if stored else 0
        uncovered = older[covered:]

        refresh_threshold = settings.context_max_tokens // 4
        if stored and estimate_history_tokens(uncovered) <= refresh_threshold:
            # Fresh enough: reuse the persisted summary, keep the small
            # uncovered remainder verbatim.
            return uncovered + recent, stored["summary"]

        summary = await self.summarize(
            stored["summary"] if stored else "",
            uncovered,
            model=model,
            local_first=local_first,
        )
        if not summary:
            # Summarizer produced nothing (e.g. provider hiccup) — fail open:
            # send the full history rather than silently dropping turns.
            return history, None
        await repo.upsert_session_summary(
            project_id, session_id, summary, len(older), owner_id=owner_id
        )
        return recent, summary


rolling_summarizer = RollingSummarizer()
