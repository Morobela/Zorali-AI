"""One-shot conversation title generation.

After the first assistant reply in a session, a single non-streamed LLM call
names the conversation ("Write a 3-6 word title"). Kept in its own module so
its LLM call is patchable independently of the chat stream, and gated behind
AUTO_TITLES_ENABLED so deployments (and the test suite) can turn it off.
"""
from __future__ import annotations

import re

from app.core.caller import Caller
from app.core.config import settings
from app.models.llm import stream_llm

_TITLE_PROMPT = (
    "Write a 3-6 word title for this conversation. Reply with the title "
    "only — no quotes, no punctuation at the end, no explanations."
)


def _clean(raw: str) -> str:
    title = re.sub(r"\s+", " ", raw).strip().strip("\"'“”‘’").rstrip(".!")
    # A runaway model reply is not a title.
    words = title.split(" ")
    if len(words) > 10:
        title = " ".join(words[:8])
    return title[:80]


class SessionTitler:
    async def title_first_exchange(
        self,
        project_id: str,
        session_id: str,
        user_message: str,
        assistant_reply: str,
        *,
        owner_id: Caller,
        model: str | None = None,
        local_first: bool = True,
    ) -> str | None:
        """Generate and store a title for a session's first exchange.

        Returns the stored title, or ``None`` when disabled, generation
        failed, or the session already has a (user-set) title. Never raises —
        a failed title must not break the chat loop.
        """
        if not settings.auto_titles_enabled:
            return None
        try:
            messages = [
                {"role": "system", "content": _TITLE_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"User: {user_message[:500]}\n\nAssistant: {assistant_reply[:500]}"
                    ),
                },
            ]
            chunks: list[str] = []
            async for token in stream_llm(messages, model=model, local_first=local_first):
                chunks.append(token)
            title = _clean("".join(chunks))
            if not title:
                return None

            from app.db.repositories import repo

            stored = await repo.set_session_title_if_empty(
                project_id, session_id, title, owner_id=owner_id
            )
            return title if stored else None
        except Exception:
            return None


session_titler = SessionTitler()
