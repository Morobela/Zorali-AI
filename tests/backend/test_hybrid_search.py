"""
Tests for the hybrid retrieval engine.

Covers each stage of the 2026 production-RAG pipeline:
  • tokenization
  • BM25 (IDF discrimination, term-frequency)
  • TF-IDF cosine
  • Reciprocal Rank Fusion
  • cross-encoder-style reranking (exact phrase / proximity)
  • contextual-retrieval chunk augmentation
  • optional dense-embedding fusion
  • end-to-end engine.search behaviour and shape
  • integration through repo.search_chunks (chat/citation contract)

All pure-Python and deterministic — no providers or network required.
"""
from __future__ import annotations

import pytest

from app.memory.hybrid_search import (
    BM25,
    HybridSearchEngine,
    LexicalReranker,
    TfidfIndex,
    build_chunk_documents,
    cosine_rank,
    engine,
    reciprocal_rank_fusion,
    tokenize,
)


# ── tokenize ────────────────────────────────────────────────────────────────

def test_tokenize_strips_punctuation_case_and_stopwords():
    assert tokenize("The Quick, Brown FOX!") == ["quick", "brown", "fox"]
    assert tokenize("   ") == []
    assert tokenize("of the and to") == []  # all stopwords


# ── BM25 ────────────────────────────────────────────────────────────────────

def _corpus():
    docs = [
        "the cat sat on the mat",
        "the dog sat on the log",
        "quantum entanglement reshapes modern physics",
    ]
    return [tokenize(d) for d in docs]


def test_bm25_idf_favours_rare_terms():
    bm25 = BM25(_corpus())
    ranked = bm25.rank(tokenize("quantum"))
    assert ranked, "rare term should match document 2"
    assert ranked[0][0] == 2


def test_bm25_more_query_matches_rank_higher():
    bm25 = BM25(_corpus())
    ranked = bm25.rank(tokenize("cat mat"))
    assert ranked[0][0] == 0  # only doc 0 contains both cat and mat


def test_bm25_no_match_returns_empty():
    bm25 = BM25(_corpus())
    assert bm25.rank(tokenize("nonexistent term")) == []


# ── TF-IDF cosine ───────────────────────────────────────────────────────────

def test_tfidf_ranks_relevant_document_first():
    tfidf = TfidfIndex(_corpus())
    ranked = tfidf.rank(tokenize("physics"))
    assert ranked and ranked[0][0] == 2


# ── Reciprocal Rank Fusion ──────────────────────────────────────────────────

def test_rrf_rewards_documents_high_in_multiple_rankers():
    r1 = [(1, 9.0), (0, 4.0), (2, 1.0)]
    r2 = [(1, 0.9), (2, 0.5), (0, 0.1)]
    fused = reciprocal_rank_fusion([r1, r2])
    assert fused[0][0] == 1  # doc 1 is top of both lists


def test_rrf_merges_disjoint_rankers():
    fused = dict(reciprocal_rank_fusion([[(0, 1.0)], [(1, 1.0)]]))
    assert set(fused) == {0, 1}


# ── Cross-encoder-style reranker ────────────────────────────────────────────

def test_reranker_prefers_exact_phrase_and_proximity():
    rr = LexicalReranker()
    q = "machine learning"
    adjacent = rr.score(q, "machine learning is a great field")
    scattered = rr.score(q, "machine intelligence and statistical learning theory")
    unrelated = rr.score(q, "cooking pasta recipes for beginners")
    assert adjacent > scattered > unrelated
    assert unrelated == 0.0


def test_reranker_handles_empty():
    rr = LexicalReranker()
    assert rr.score("", "anything") == 0.0
    assert rr.score("query", "") == 0.0


# ── Dense embedding signal ──────────────────────────────────────────────────

def test_cosine_rank_orders_by_similarity_and_drops_orthogonal():
    ranked = cosine_rank([1.0, 0.0], [[1.0, 0.0], [0.0, 1.0], [0.7, 0.7]])
    order = [idx for idx, _ in ranked]
    assert order[0] == 0          # identical direction
    assert 1 not in order         # orthogonal vector dropped (cos == 0)
    assert 2 in order


# ── Engine: end-to-end ──────────────────────────────────────────────────────

def test_engine_search_returns_most_relevant_first():
    docs = [
        {"text": "Paris is the capital of France"},
        {"text": "Berlin is the capital of Germany"},
        {"text": "this recipe needs two eggs and a cup of flour"},
    ]
    results = engine.search("capital of France", docs, top_k=2)
    assert len(results) == 2
    assert "France" in results[0].doc["text"]


def test_engine_search_respects_top_k_and_empty_inputs():
    docs = [{"text": "alpha beta"}, {"text": "beta gamma"}, {"text": "gamma delta"}]
    assert len(engine.search("beta", docs, top_k=1)) == 1
    assert engine.search("", docs) == []
    assert engine.search("beta", []) == []
    assert engine.search("   ", docs) == []


def test_engine_search_result_carries_score_and_components():
    docs = [{"text": "neural networks learn representations"}]
    results = engine.search("neural networks", docs)
    assert results
    assert isinstance(results[0].score, float)
    assert "rerank" in results[0].components


def test_engine_rerank_disabled_still_returns_results():
    no_rerank = HybridSearchEngine(rerank=False)
    docs = [{"text": "alpha signal"}, {"text": "beta noise"}]
    results = no_rerank.search("alpha", docs)
    assert results and results[0].doc["text"].startswith("alpha")


# ── Contextual retrieval ────────────────────────────────────────────────────

def test_contextual_retrieval_makes_chunks_findable_via_document_context():
    files = [
        {
            "id": "f1",
            "filename": "france_travel_guide.md",
            "extracted_text": "Paris France Eiffel Seine travel tourism guide",
            "chunks": [
                {"id": 0, "text": "It has many museums and quiet cafes."},
                {"id": 1, "text": "The riverside walk is pleasant at dusk."},
            ],
        }
    ]
    query = "France travel guide"

    with_ctx = engine.search(query, build_chunk_documents(files, contextual=True), top_k=2)
    without_ctx = engine.search(query, build_chunk_documents(files, contextual=False), top_k=2)

    # The chunk texts contain none of the query terms; only the contextual
    # header (filename + document keywords) does. Context must add recall.
    assert len(with_ctx) >= 1
    assert len(with_ctx) > len(without_ctx)
    assert all(r.doc["file_id"] == "f1" for r in with_ctx)


def test_build_chunk_documents_preserves_display_text():
    files = [
        {"id": "f1", "filename": "a.md", "extracted_text": "hello world",
         "chunks": [{"id": 0, "text": "raw chunk body"}]}
    ]
    docs = build_chunk_documents(files, contextual=True)
    assert docs[0]["text"] == "raw chunk body"          # display text untouched
    assert "a.md" in docs[0]["search_text"]             # header only in search text


# ── Integration: repo.search_chunks contract ────────────────────────────────

def test_repo_search_chunks_preserves_shape_and_improves_ranking():
    from app.db.repositories import repo

    project = repo.create_project("hybrid-search-test", "rag")
    pid = project["id"]
    chunks = [
        {"id": 0, "text": "The quarterly revenue report shows strong year over year growth"},
        {"id": 1, "text": "the and or of to in on with as by for"},  # stopword noise
        {"id": 2, "text": "Employees enjoyed the summer picnic in the park"},
    ]
    repo.save_file(
        project_id=pid,
        filename="report.md",
        content=b"x",
        extracted_text=" ".join(c["text"] for c in chunks),
        chunks=chunks,
    )

    results = repo.search_chunks(pid, "revenue report", limit=3)
    assert results, "should retrieve at least one chunk"
    assert set(results[0].keys()) == {"file_id", "filename", "chunk_id", "text", "score"}
    assert results[0]["chunk_id"] == 0           # most relevant chunk first
    assert results[0]["filename"] == "report.md"

    assert repo.search_chunks(pid, "", limit=3) == []


def test_repo_search_chunks_semantic_over_naive_overlap():
    """A discriminative rare term must beat a chunk full of common words."""
    from app.db.repositories import repo

    project = repo.create_project("hybrid-idf-test", "rag")
    pid = project["id"]
    chunks = [
        {"id": 0, "text": "general notes about the project and the team and the plan"},
        {"id": 1, "text": "the kubernetes deployment manifest defines three replicas"},
    ]
    repo.save_file(
        project_id=pid, filename="notes.md", content=b"x",
        extracted_text=" ".join(c["text"] for c in chunks), chunks=chunks,
    )
    results = repo.search_chunks(pid, "kubernetes deployment", limit=2)
    assert results[0]["chunk_id"] == 1
