"""Graph memory: extract (subject, relation, object) triples from saved
memories and retrieve them by following entity relationships.

Why a graph and not just similarity search: a query like "where does Charles
work?" shares almost no vocabulary with the stored memory "Charles is employed
at Acme" — but a triple (charles, works_at, acme) matches on the *entity* and
answers directly. One-hop expansion then pulls in related facts about the
matched entities ("acme —uses→ python"), Mem0/GraphRAG-style, without needing
an LLM in the loop.

Extraction is deterministic (regex patterns over sentences), so it works
offline, costs nothing, and is unit-testable. The pattern list favours
precision over recall: a missed triple only degrades to text search, while a
wrong triple pollutes every future answer.
"""
from __future__ import annotations

import re

from app.db.repositories import repo

# Words too generic to be graph entities or match anchors.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "is", "are", "was", "were", "to", "of",
    "for", "on", "in", "it", "with", "as", "by", "at", "be", "this", "that",
    "from", "does", "do", "did", "who", "what", "where", "when", "which",
    "how", "why", "my", "me", "his", "her", "their", "our", "your",
}

# Normalise verb variants to one canonical relation.
_RELATION_ALIASES = {
    "love": "likes", "loves": "likes", "like": "likes", "likes": "likes",
    "enjoy": "likes", "enjoys": "likes",
    "prefer": "prefers", "prefers": "prefers",
    "hate": "dislikes", "hates": "dislikes",
    "dislike": "dislikes", "dislikes": "dislikes",
    "use": "uses", "uses": "uses",
}

# An entity: starts with a word character, then a short run of words,
# spaces, dots, apostrophes or hyphens. Non-greedy so verbs are not swallowed.
_ENT = r"([\w][\w .'’-]{0,60}?)"

# First-person patterns run before third-person so "I work at X" is not
# parsed as subject "I". Order within each group matters: specific verbs
# before the generic "is".
_FIRST_PERSON_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bmy name is " + _ENT + r"$", re.IGNORECASE), "name"),
    (re.compile(r"\bi (?:really )?(?:like|love|enjoy) " + _ENT + r"$", re.IGNORECASE), "likes"),
    (re.compile(r"\bi prefer " + _ENT + r"$", re.IGNORECASE), "prefers"),
    (re.compile(r"\bi (?:hate|dislike) " + _ENT + r"$", re.IGNORECASE), "dislikes"),
    (re.compile(r"\bi work (?:at|for) " + _ENT + r"$", re.IGNORECASE), "works_at"),
    (re.compile(r"\bi live in " + _ENT + r"$", re.IGNORECASE), "lives_in"),
    (re.compile(r"\bi(?:'m| am) from " + _ENT + r"$", re.IGNORECASE), "from"),
    (re.compile(r"\bi use " + _ENT + r"$", re.IGNORECASE), "uses"),
    (re.compile(r"\bi(?:'m| am) (?:a |an )?" + _ENT + r"$", re.IGNORECASE), "is"),
]

_THIRD_PERSON_PATTERNS: list[re.Pattern] = [
    re.compile(_ENT + r" (likes|loves|enjoys|prefers|hates|dislikes) " + _ENT + r"$", re.IGNORECASE),
    re.compile(_ENT + r" works (?:at|for) " + _ENT + r"$", re.IGNORECASE),
    re.compile(_ENT + r" lives in " + _ENT + r"$", re.IGNORECASE),
    re.compile(_ENT + r" is (?:employed|based) (?:at|in) " + _ENT + r"$", re.IGNORECASE),
    re.compile(_ENT + r" uses " + _ENT + r"$", re.IGNORECASE),
    re.compile(_ENT + r" is (?:a |an )?" + _ENT + r"$", re.IGNORECASE),
]

# Relation implied by each third-person pattern (parallel to the list above;
# None means the relation is the captured verb group).
_THIRD_PERSON_RELATIONS: list[str | None] = [None, "works_at", "lives_in", "works_at", "uses", "is"]


def _norm_entity(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip(" .,'’\"-").lower()
    for article in ("the ", "a ", "an "):
        if cleaned.startswith(article):
            cleaned = cleaned[len(article):]
    return cleaned


def _tokens(value: str) -> set[str]:
    return {
        tok
        for tok in re.findall(r"[\w'-]+", value.lower())
        if tok not in _STOPWORDS and len(tok) > 1
    }


def extract_triples(text: str) -> list[tuple[str, str, str]]:
    """Extract (subject, relation, object) facts from free text.

    First-person statements attach to the pseudo-entity ``user`` so
    "I work at Acme" and "where do I work?" meet at the same node.
    """
    triples: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for sentence in re.split(r"[.;!?\n]+", text):
        sentence = sentence.strip()
        if not sentence:
            continue

        matched_first_person = False
        for pattern, relation in _FIRST_PERSON_PATTERNS:
            m = pattern.search(sentence)
            if m:
                obj = _norm_entity(m.group(1))
                if obj and obj not in _STOPWORDS:
                    triple = ("user", relation, obj)
                    if triple not in seen:
                        seen.add(triple)
                        triples.append(triple)
                matched_first_person = True
                break
        if matched_first_person:
            continue

        for pattern, implied in zip(_THIRD_PERSON_PATTERNS, _THIRD_PERSON_RELATIONS):
            m = pattern.search(sentence)
            if not m:
                continue
            groups = m.groups()
            if implied is None:
                subject, verb, obj = groups
                relation = _RELATION_ALIASES.get(verb.lower(), verb.lower())
            else:
                subject, obj = groups[0], groups[-1]
                relation = implied
            subject, obj = _norm_entity(subject), _norm_entity(obj)
            if (
                subject and obj and subject != obj
                and subject not in _STOPWORDS and obj not in _STOPWORDS
            ):
                triple = (subject, relation, obj)
                if triple not in seen:
                    seen.add(triple)
                    triples.append(triple)
            break

    return triples


class KnowledgeGraph:
    """Postgres-backed triple store scoped per project + owner."""

    async def extract_and_store(
        self, text: str, project_id: str, owner_id: str, memory_id: str
    ) -> list[dict]:
        """Extract triples from ``text`` and persist them against ``memory_id``.

        Returns the stored triples (possibly empty — not every memory contains
        an extractable fact, and that is fine: text search still covers it).
        """
        triples = extract_triples(text)
        return await repo.save_memory_triples(memory_id, project_id, owner_id, triples)

    async def query(
        self, query: str, project_id: str, owner_id: str, limit: int = 12
    ) -> list[dict]:
        """Triples relevant to ``query``: direct entity matches plus one hop.

        Pass 1 matches triples whose subject or object shares a token with the
        query ("charles", or "I/my" → the ``user`` node). Pass 2 expands one
        hop: any triple touching an entity seen in pass-1 matches, so asking
        about charles also surfaces what charles's employer uses.
        """
        rows = await repo.list_memory_triples(project_id, owner_id)
        if not rows:
            return []

        q_tokens = _tokens(query)
        # First-person questions ("where do I work?") anchor to the user node.
        if re.search(r"\b(i|me|my|mine)\b", query.lower()):
            q_tokens.add("user")
        if not q_tokens:
            return []

        direct: list[dict] = []
        direct_ids: set[int] = set()
        entities: set[str] = set()
        for row in rows:
            side_tokens = _tokens(row["subject"]) | _tokens(row["object"]) | {row["subject"], row["object"]}
            if q_tokens & side_tokens:
                direct.append(row)
                direct_ids.add(row["id"])
                entities.add(row["subject"])
                entities.add(row["object"])

        one_hop = [
            row
            for row in rows
            if row["id"] not in direct_ids
            and (row["subject"] in entities or row["object"] in entities)
        ]
        return (direct + one_hop)[:limit]

    async def graph_context_for_query(
        self, query: str, project_id: str, owner_id: str, limit: int = 12
    ) -> str:
        """Formatted fact lines for prompt injection ('' when nothing matches)."""
        matched = await self.query(query, project_id, owner_id, limit=limit)
        return "\n".join(
            f"{t['subject']} —{t['relation']}→ {t['object']}" for t in matched
        )


knowledge_graph = KnowledgeGraph()
