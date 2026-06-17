"""
Hybrid retrieval engine — the 2026 production-RAG standard, in pure Python.

Modern retrieval has moved well past single-signal keyword matching. The
current best-practice pipeline (and the one implemented here) is two stages:

    1. Broad recall   — score every chunk with several *independent* rankers
                        (lexical BM25, TF-IDF cosine, and optionally a dense
                        embedding cosine) and fuse them with Reciprocal Rank
                        Fusion (RRF). This is "hybrid search".
    2. Precise rerank — take the fused shortlist and re-score each candidate
                        with a query-aware "cross-encoder-style" scorer that
                        looks at the query and chunk *together* (exact phrase
                        hits, query-term coverage, term proximity). This is the
                        single biggest quality lever in production RAG.

On top of that we apply *contextual retrieval*: each chunk is indexed together
with a short header describing its source document, so a chunk remains findable
even when the query terms only appear in surrounding document context. This
mirrors the contextual-retrieval technique that has been shown to cut top-k
retrieval failures dramatically.

Everything here is dependency-free and deterministic so it behaves identically
in CI, offline, and in production. Dense embeddings are an *optional* signal:
when the caller supplies vectors they are fused in as a third ranker; when they
are absent the engine degrades gracefully to lexical hybrid + rerank.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from string import punctuation
from typing import Sequence

# A compact English stop-word list. Kept local so the engine has no internal
# imports and can be reasoned about in isolation.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "if", "is", "are", "was", "were",
        "be", "been", "being", "to", "of", "for", "on", "in", "it", "its",
        "with", "as", "by", "at", "be", "this", "that", "these", "those",
        "from", "into", "over", "under", "then", "than", "so", "such", "can",
        "could", "should", "would", "will", "shall", "may", "might", "do",
        "does", "did", "has", "have", "had", "i", "you", "he", "she", "we",
        "they", "me", "him", "her", "us", "them", "my", "your", "our", "their",
    }
)

_PUNCT_RE = re.compile(f"[{re.escape(punctuation)}]")


def tokenize(text: str) -> list[str]:
    """Lower-case, strip punctuation, drop stop-words."""
    cleaned = _PUNCT_RE.sub(" ", text.lower())
    return [tok for tok in cleaned.split() if tok and tok not in _STOPWORDS]


# ── Stage 1a: BM25 (Okapi) ──────────────────────────────────────────────────

class BM25:
    """Okapi BM25 — IDF-weighted, length-normalised keyword ranking.

    This is a strict upgrade over raw token-overlap: rare, discriminative terms
    are weighted far above common ones (IDF), term saturation is handled (k1),
    and long documents no longer win just by being long (b length-norm).
    """

    def __init__(self, corpus_tokens: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.n_docs = len(corpus_tokens)
        self.doc_len = [len(d) for d in corpus_tokens]
        self.avgdl = (sum(self.doc_len) / self.n_docs) if self.n_docs else 0.0

        self.tf: list[dict[str, int]] = []
        df: dict[str, int] = {}
        for doc in corpus_tokens:
            freqs: dict[str, int] = {}
            for tok in doc:
                freqs[tok] = freqs.get(tok, 0) + 1
            self.tf.append(freqs)
            for tok in freqs:
                df[tok] = df.get(tok, 0) + 1

        # Smoothed IDF that stays non-negative for terms present in every doc.
        self.idf: dict[str, float] = {
            tok: math.log(1 + (self.n_docs - d + 0.5) / (d + 0.5)) for tok, d in df.items()
        }

    def score(self, query_tokens: Sequence[str], idx: int) -> float:
        freqs = self.tf[idx]
        dl = self.doc_len[idx]
        avgdl = self.avgdl or 1.0
        total = 0.0
        for tok in query_tokens:
            f = freqs.get(tok)
            if not f:
                continue
            idf = self.idf.get(tok, 0.0)
            denom = f + self.k1 * (1 - self.b + self.b * dl / avgdl)
            total += idf * (f * (self.k1 + 1)) / (denom or 1.0)
        return total

    def rank(self, query_tokens: Sequence[str]) -> list[tuple[int, float]]:
        scored = [(i, self.score(query_tokens, i)) for i in range(self.n_docs)]
        scored = [pair for pair in scored if pair[1] > 0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored


# ── Stage 1b: TF-IDF cosine ─────────────────────────────────────────────────

class TfidfIndex:
    """Vector-space TF-IDF cosine similarity — an independent lexical signal.

    BM25 and TF-IDF agree often but not always; fusing two correlated-but-
    distinct rankers is what makes hybrid search robust to the failure modes of
    either one alone.
    """

    def __init__(self, corpus_tokens: list[list[str]]):
        self.n_docs = len(corpus_tokens)
        df: dict[str, int] = {}
        tf: list[dict[str, int]] = []
        for doc in corpus_tokens:
            freqs: dict[str, int] = {}
            for tok in doc:
                freqs[tok] = freqs.get(tok, 0) + 1
            tf.append(freqs)
            for tok in freqs:
                df[tok] = df.get(tok, 0) + 1

        self.idf = {tok: math.log((1 + self.n_docs) / (1 + d)) + 1.0 for tok, d in df.items()}

        self.doc_vecs: list[dict[str, float]] = []
        self.doc_norms: list[float] = []
        for freqs in tf:
            vec = {tok: (1 + math.log(f)) * self.idf.get(tok, 0.0) for tok, f in freqs.items()}
            norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
            self.doc_vecs.append(vec)
            self.doc_norms.append(norm)

    def _query_vec(self, query_tokens: Sequence[str]) -> tuple[dict[str, float], float]:
        freqs: dict[str, int] = {}
        for tok in query_tokens:
            freqs[tok] = freqs.get(tok, 0) + 1
        vec = {
            tok: (1 + math.log(f)) * self.idf[tok]
            for tok, f in freqs.items()
            if tok in self.idf
        }
        norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
        return vec, norm

    def rank(self, query_tokens: Sequence[str]) -> list[tuple[int, float]]:
        qvec, qnorm = self._query_vec(query_tokens)
        if not qvec:
            return []
        scored: list[tuple[int, float]] = []
        for i, dvec in enumerate(self.doc_vecs):
            small, large = (qvec, dvec) if len(qvec) < len(dvec) else (dvec, qvec)
            dot = sum(w * large.get(tok, 0.0) for tok, w in small.items())
            if dot <= 0:
                continue
            scored.append((i, dot / (qnorm * self.doc_norms[i])))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored


# ── Optional dense signal ───────────────────────────────────────────────────

def cosine_rank(query_vec: Sequence[float], doc_vecs: Sequence[Sequence[float]]) -> list[tuple[int, float]]:
    """Rank documents by cosine similarity against a query embedding."""
    qn = math.sqrt(sum(x * x for x in query_vec)) or 1.0
    scored: list[tuple[int, float]] = []
    for i, dv in enumerate(doc_vecs):
        dot = sum(a * b for a, b in zip(query_vec, dv))
        if dot <= 0:
            continue
        dn = math.sqrt(sum(y * y for y in dv)) or 1.0
        scored.append((i, dot / (qn * dn)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


# ── Stage 1c: Reciprocal Rank Fusion ────────────────────────────────────────

def reciprocal_rank_fusion(
    rankings: list[list[tuple[int, float]]], k: int = 60
) -> list[tuple[int, float]]:
    """Fuse several ranked lists into one.

    RRF combines rankers by *rank position* rather than raw score, so signals on
    wildly different scales (BM25 points vs. cosine in [0,1]) merge cleanly. A
    document ranked highly by multiple rankers floats to the top.
    """
    fused: dict[int, float] = {}
    for ranking in rankings:
        for position, (idx, _score) in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + position + 1)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


# ── Stage 2: cross-encoder-style reranker ───────────────────────────────────

class LexicalReranker:
    """Query-aware joint scorer approximating a cross-encoder.

    The recall rankers score the query and a document independently. A real
    cross-encoder reads the pair together and is the standard precision stage of
    production RAG. We approximate that joint view with features that per-term
    statistics cannot see:

      • coverage     — fraction of distinct query terms present
      • exact_phrase — the (normalised) query appears verbatim in the chunk
      • proximity    — how tightly the query terms cluster together
      • bigram       — shared adjacent word pairs

    These reward chunks where the query terms actually appear *as the query*,
    not merely scattered across a long passage.
    """

    weights = {"coverage": 0.45, "exact_phrase": 0.25, "proximity": 0.20, "bigram": 0.10}

    def score(self, query: str, text: str, idf: dict[str, float] | None = None) -> float:
        q_tokens = tokenize(query)
        d_tokens = tokenize(text)
        if not q_tokens or not d_tokens:
            return 0.0

        q_set = set(q_tokens)
        d_set = set(d_tokens)
        present = q_set & d_set

        # Coverage rewards matching the query's *salient* terms. When corpus IDF
        # is available we weight each term by its rarity, so a chunk that matches
        # the one discriminative term beats a keyword-stuffed chunk that matches
        # several common ones — exactly what a cross-encoder learns to do.
        if idf:
            total_w = sum(idf.get(t, 0.0) for t in q_set)
            coverage = (sum(idf.get(t, 0.0) for t in present) / total_w) if total_w else 0.0
        else:
            coverage = len(present) / len(q_set)

        nq = " ".join(q_tokens)
        nd = " ".join(d_tokens)
        exact = 1.0 if nq and nq in nd else 0.0

        q_bi = set(zip(q_tokens, q_tokens[1:]))
        d_bi = set(zip(d_tokens, d_tokens[1:]))
        bigram = (len(q_bi & d_bi) / len(q_bi)) if q_bi else 0.0

        proximity = self._proximity(present, d_tokens)

        w = self.weights
        return (
            w["coverage"] * coverage
            + w["exact_phrase"] * exact
            + w["proximity"] * proximity
            + w["bigram"] * bigram
        )

    @staticmethod
    def _proximity(present: set[str], d_tokens: list[str]) -> float:
        """Smallest token window covering all present query terms → in (0, 1].

        1.0 means the matched terms are perfectly adjacent; smaller means they
        are spread out across the chunk.
        """
        if not present:
            return 0.0
        need = len(present)
        if need == 1:
            return 1.0

        best: int | None = None
        counts: dict[str, int] = {}
        distinct = 0
        left = 0
        for right, tok in enumerate(d_tokens):
            if tok in present:
                counts[tok] = counts.get(tok, 0) + 1
                if counts[tok] == 1:
                    distinct += 1
            while distinct == need:
                span = right - left + 1
                if best is None or span < best:
                    best = span
                lt = d_tokens[left]
                if lt in present:
                    counts[lt] -= 1
                    if counts[lt] == 0:
                        distinct -= 1
                left += 1
        if not best:
            return 0.0
        return need / best


# ── Results & engine ────────────────────────────────────────────────────────

@dataclass
class SearchResult:
    doc: dict
    score: float
    components: dict = field(default_factory=dict)


class HybridSearchEngine:
    """Two-stage retrieval: hybrid fusion (recall) → reranking (precision)."""

    def __init__(
        self,
        *,
        rrf_k: int = 60,
        candidate_pool: int = 20,
        rerank: bool = True,
        rerank_weight: float = 0.65,
    ):
        self.rrf_k = rrf_k
        self.candidate_pool = candidate_pool
        self.rerank = rerank
        self.rerank_weight = rerank_weight

    def search(
        self,
        query: str,
        documents: list[dict],
        top_k: int = 5,
        *,
        embed_query: Sequence[float] | None = None,
        doc_embeddings: Sequence[Sequence[float]] | None = None,
    ) -> list[SearchResult]:
        if not query or not query.strip() or not documents:
            return []
        q_tokens = tokenize(query)
        if not q_tokens:
            return []

        # Index over the *searchable* text (contextualised when available),
        # but always return the original chunk text for display.
        texts = [d.get("search_text") or d.get("text", "") for d in documents]
        corpus_tokens = [tokenize(t) for t in texts]

        bm25 = BM25(corpus_tokens)
        tfidf = TfidfIndex(corpus_tokens)
        rankings = [bm25.rank(q_tokens), tfidf.rank(q_tokens)]

        if embed_query is not None and doc_embeddings is not None and len(doc_embeddings) == len(documents):
            rankings.append(cosine_rank(embed_query, doc_embeddings))

        fused = reciprocal_rank_fusion(rankings, k=self.rrf_k)
        if not fused:
            return []

        candidates = fused[: self.candidate_pool]
        if not self.rerank:
            return [
                SearchResult(doc=documents[idx], score=round(float(s), 6), components={"fused": s})
                for idx, s in candidates[:top_k]
            ]

        max_fused = max(s for _, s in candidates) or 1.0
        reranker = LexicalReranker()
        rescored: list[tuple[int, float, dict]] = []
        for idx, fused_score in candidates:
            rer = reranker.score(query, documents[idx].get("text", ""), idf=bm25.idf)
            fused_norm = fused_score / max_fused
            final = self.rerank_weight * rer + (1 - self.rerank_weight) * fused_norm
            rescored.append(
                (idx, final, {"rerank": round(rer, 6), "fused": round(fused_score, 6)})
            )

        rescored.sort(key=lambda x: (x[1], x[2]["fused"]), reverse=True)
        return [
            SearchResult(doc=documents[idx], score=round(float(final), 6), components=comp)
            for idx, final, comp in rescored[:top_k]
        ]


# ── Document builders (contextual retrieval) ────────────────────────────────

def _document_keywords(text: str, top: int = 8) -> list[str]:
    """Cheap, deterministic document-level keywords (highest raw frequency)."""
    freqs: dict[str, int] = {}
    for tok in tokenize(text):
        freqs[tok] = freqs.get(tok, 0) + 1
    return [tok for tok, _ in sorted(freqs.items(), key=lambda x: x[1], reverse=True)[:top]]


def build_chunk_documents(files: list[dict], contextual: bool = True) -> list[dict]:
    """Flatten project files into searchable chunk documents.

    With ``contextual=True`` each chunk's *searchable* text is prefixed with a
    small header — the file name and the document's top keywords — so a chunk
    stays retrievable even when the query matches the document's overall topic
    rather than the chunk's literal words. The returned ``text`` field is always
    the untouched chunk so citations and prompts show the real content.
    """
    documents: list[dict] = []
    for f in files:
        filename = f.get("filename", "")
        doc_keywords = _document_keywords(f.get("extracted_text", "")) if contextual else []
        header = ""
        if contextual:
            header = f"{filename} :: {' '.join(doc_keywords)}".strip()
        for c in f.get("chunks", []):
            chunk_text = c.get("text", "")
            search_text = f"{header}\n{chunk_text}" if header else chunk_text
            documents.append(
                {
                    "file_id": f.get("id"),
                    "filename": filename,
                    "chunk_id": c.get("id"),
                    "text": chunk_text,
                    "search_text": search_text,
                }
            )
    return documents


def _engine_from_settings() -> HybridSearchEngine:
    try:
        from app.core.config import settings

        return HybridSearchEngine(
            rrf_k=settings.rag_rrf_k,
            candidate_pool=settings.rag_candidate_pool,
            rerank=settings.rag_rerank_enabled,
        )
    except Exception:
        return HybridSearchEngine()


# Shared singleton used across the retrieval paths (chat RAG, memory, agents).
engine = _engine_from_settings()
