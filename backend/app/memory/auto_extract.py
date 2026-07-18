"""Automatic memory extraction with a human review step.

After each completed chat turn, the user's message is scanned for durable
facts ("I work at Acme", "my deadline is Friday"). Candidates are stored as
``status="pending"`` memories — they are NOT searchable and never enter a
prompt until the user accepts them in the Memory panel (accepted → normal
memory with graph triples, rejected → deleted).

Extraction strategy (gated behind AUTO_MEMORY_ENABLED):
1. Pattern pass: sentences the deterministic triple extractor
   (``knowledge_graph.extract_triples``) fires on become candidates — free,
   offline, precise.
2. LLM fallback: only when the pattern pass finds nothing, one non-streamed
   LLM call extracts fact phrasings the patterns miss ("remember that …").
Candidates near-identical to an existing memory (any status) for the same
owner+project are skipped, so repeating yourself does not pile up duplicates.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.core.config import settings
from app.memory.knowledge_graph import extract_triples
from app.models.llm import stream_llm

# At most this many candidates per turn, each capped in length.
_MAX_CANDIDATES = 5
_MAX_CANDIDATE_CHARS = 300
# Similarity ratio at or above which a candidate counts as a duplicate.
_DEDUPE_RATIO = 0.9
# Messages shorter than this can't contain a durable fact worth reviewing.
_MIN_MESSAGE_CHARS = 8

_FALLBACK_PROMPT = (
    "Extract durable personal or project facts worth remembering from the "
    "user's message: preferences, deadlines, names, roles, decisions, "
    "constraints. Output each fact on its own line, phrased as a short "
    "standalone statement. If the message contains no durable fact (small "
    "talk, a question, a one-off request), output exactly NONE."
)


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def _is_duplicate(candidate: str, existing_texts: list[str]) -> bool:
    norm = _normalize(candidate)
    if not norm:
        return True
    for text in existing_texts:
        other = _normalize(text)
        if norm == other or SequenceMatcher(None, norm, other).ratio() >= _DEDUPE_RATIO:
            return True
    return False


def pattern_candidates(message: str) -> list[str]:
    """Sentences the deterministic triple extractor recognises as facts."""
    candidates = []
    for sentence in re.split(r"[.;!?\n]+", message):
        sentence = sentence.strip()
        if sentence and extract_triples(sentence):
            candidates.append(sentence[:_MAX_CANDIDATE_CHARS])
    return candidates[:_MAX_CANDIDATES]


async def llm_fallback_candidates(
    message: str, *, model: str | None = None, local_first: bool = True
) -> list[str]:
    """One non-streamed LLM call for fact phrasings the patterns miss."""
    messages = [
        {"role": "system", "content": _FALLBACK_PROMPT},
        {"role": "user", "content": message[:2000]},
    ]
    chunks: list[str] = []
    async for token in stream_llm(messages, model=model, local_first=local_first):
        chunks.append(token)
    reply = "".join(chunks).strip()
    if not reply or reply.upper().startswith("NONE"):
        return []
    lines = [line.strip(" -•\t") for line in reply.splitlines()]
    return [line[:_MAX_CANDIDATE_CHARS] for line in lines if line][:_MAX_CANDIDATES]


class AutoMemoryExtractor:
    async def process_turn(
        self,
        project_id: str,
        user_message: str,
        owner_id: str,
        *,
        model: str | None = None,
        local_first: bool = True,
    ) -> list[dict]:
        """Extract and store pending candidates for one completed chat turn.

        Returns the stored candidates (empty when disabled, nothing found,
        or everything deduplicated away). Never raises — a failed extraction
        must not break the chat loop that fires it.
        """
        if not settings.auto_memory_enabled:
            return []
        message = (user_message or "").strip()
        if len(message) < _MIN_MESSAGE_CHARS:
            return []
        try:
            candidates = pattern_candidates(message)
            if not candidates:
                candidates = await llm_fallback_candidates(
                    message, model=model, local_first=local_first
                )
            if not candidates:
                return []

            from app.db.repositories import repo

            existing = await repo.list_memories(project_id, owner_id, status=None)
            existing_texts = [m["text"] for m in existing]
            stored: list[dict] = []
            for text in candidates:
                if _is_duplicate(text, existing_texts):
                    continue
                row = await repo.save_memory(project_id, owner_id, text, status="pending")
                stored.append(row)
                existing_texts.append(text)  # dedupe within the same turn too
            return stored
        except Exception:
            return []


auto_memory = AutoMemoryExtractor()
