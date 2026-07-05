"""
Tests for the hybrid retrieval engine.

Covers each stage of the pipeline:
  • tokenization
  • BM25 (IDF discrimination, term-frequency)
  • TF-IDF cosine
  • Reciprocal Rank Fusion
  • LexicalFeatureReranker (exact phrase / proximity / IDF-weighted coverage)
  • cosine_rank (including dimension mismatch guard)
  • contextual-retrieval chunk augmentation
  • index caching
  • end-to-end engine.search behavior and shape
  • integration through repo.search_chunks (chat/citation contract)
  • paraphrase retrieval gap (what requires dense embeddings)

All pure-Python and deterministic — no providers or network required.
"""
from __future__ import annotations

import pytest

from app.memory.hybrid_search import (
    BM25,
    HybridSearchEngine,
    LexicalFeatureReranker,
    TfidfIndex,
    _INDEX_CACHE,
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


# ── LexicalFeatureReranker ──────────────────────────────────────────────────

def test_reranker_prefers_exact_phrase_and_proximity():
    rr = LexicalFeatureReranker()
    q = "machine learning"
    adjacent = rr.score(q, "machine learning is a great field")
    scattered = rr.score(q, "machine intelligence and statistical learning theory")
    unrelated = rr.score(q, "cooking pasta recipes for beginners")
    assert adjacent > scattered > unrelated
    assert unrelated == 0.0


def test_reranker_handles_empty():
    rr = LexicalFeatureReranker()
    assert rr.score("", "anything") == 0.0
    assert rr.score("query", "") == 0.0


def test_reranker_idf_weights_rare_over_common_terms():
    """A chunk matching a single rare term must beat one matching several common terms."""
    rr = LexicalFeatureReranker()
    # Simulate an IDF map where 'kubernetes' is rare and common words are cheap
    idf = {"kubernetes": 8.0, "configure": 0.5, "database": 0.5, "connection": 0.5, "size": 0.5}
    rare_match = rr.score("kubernetes configuration", "the kubernetes cluster manifest", idf=idf)
    common_match = rr.score("kubernetes configuration", "configure the database connection size and configure more", idf=idf)
    assert rare_match > common_match


def test_reranker_exact_phrase_beats_scattered():
    """Exact phrase in chunk beats scattered individual terms."""
    rr = LexicalFeatureReranker()
    q = "error handling"
    exact = rr.score(q, "error handling: wrap calls in try/except")
    scattered = rr.score(q, "an error occurred while handling the upload see handling notes error logs")
    assert exact > scattered


# ── cosine_rank ─────────────────────────────────────────────────────────────

def test_cosine_rank_orders_by_similarity_and_drops_orthogonal():
    ranked = cosine_rank([1.0, 0.0], [[1.0, 0.0], [0.0, 1.0], [0.7, 0.7]])
    order = [idx for idx, _ in ranked]
    assert order[0] == 0          # identical direction
    assert 1 not in order         # orthogonal vector dropped (cos == 0)
    assert 2 in order


def test_cosine_rank_skips_mismatched_dimensions():
    """Dimension mismatch must be silently skipped, not crash or truncate."""
    result = cosine_rank([1.0, 0.0, 0.0], [[1.0, 0.0], [1.0, 0.0, 0.0]])
    # Only the dim-3 doc should survive
    assert len(result) == 1
    assert result[0][0] == 1


def test_cosine_rank_empty_query_returns_empty():
    assert cosine_rank([], [[1.0, 0.0]]) == []


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


def test_engine_exact_phrase_beats_scattered_terms():
    """Reranker must rank the exact-phrase chunk above the keyword-scattered one."""
    docs = [
        {"text": "An error occurred while handling the upload. See handling notes and error logs for the trace."},
        {"text": "Error handling: wrap the call in a try/except and log the exception cleanly."},
    ]
    results = engine.search("error handling", docs, top_k=2)
    assert results[0].doc["text"].startswith("Error handling:")


def test_engine_guards_zero_candidate_pool():
    """candidate_pool=0 must not crash (clamped to 1 internally)."""
    eng = HybridSearchEngine(candidate_pool=0, rerank=False)
    docs = [{"text": "alpha beta gamma"}]
    # Should not raise; may return 0 or 1 results
    eng.search("alpha", docs, top_k=1)


def test_engine_extra_rankings_fused_via_rrf():
    """A pre-computed dense ranking passed as extra_rankings must be merged by RRF."""
    docs = [
        {"text": "cooking pasta recipes for beginners"},
        {"text": "machine learning optimization techniques"},
    ]
    # Simulate dense ranking that strongly prefers doc 1
    dense_ranking = [(1, 0.95), (0, 0.1)]
    results = engine.search("machine learning", docs, top_k=2, extra_rankings=[dense_ranking])
    assert results and results[0].doc["text"].startswith("machine")


def test_reranker_boost_preserves_semantic_only_match():
    """Semantic-only candidates (lexical=0) must not be crushed below their fused score."""
    # This tests the multiplicative-boost formula: final = fused × (1 + weight × lex)
    # A doc with fused=1.0 and lex=0 gets final=1.0 — it keeps its full fused score.
    eng = HybridSearchEngine(rerank=True, rerank_weight=0.5, candidate_pool=5)
    # Doc 0: shares query words (lexical hit) but conceptually unrelated
    # Doc 1: shares NO words with query but is in candidates via extra_rankings (simulating dense)
    docs = [
        {"text": "query alpha beta gamma tokens appear here"},
        {"text": "completely unrelated vocabulary zebra xylophone"},
    ]
    # Pre-inject doc 1 at top of dense ranking (simulates perfect semantic match)
    dense_ranking = [(1, 1.0), (0, 0.1)]
    results = eng.search("query alpha", docs, top_k=2, extra_rankings=[dense_ranking])
    # Doc 1 should appear in results (semantic match not crushed)
    result_texts = [r.doc["text"] for r in results]
    assert any("zebra" in t for t in result_texts), "Semantic-only match must survive reranking"


# ── Index cache ─────────────────────────────────────────────────────────────

def test_index_cache_populated_on_first_search():
    _INDEX_CACHE.clear()
    docs = [{"text": "caching test document unique phrase zyzzyva"}]
    engine.search("zyzzyva", docs)
    assert len(_INDEX_CACHE) >= 1


def test_index_cache_reused_on_second_search():
    docs = [{"text": "cache reuse test flobberwick unique token"}]
    engine.search("flobberwick", docs)
    size_before = len(_INDEX_CACHE)
    engine.search("flobberwick", docs)
    assert len(_INDEX_CACHE) == size_before  # no new entry added


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
    # Without context the chunk texts contain none of the query terms; context adds recall.
    assert len(with_ctx) >= 1
    assert len(with_ctx) > len(without_ctx)
    assert all(r.doc["file_id"] == "f1" for r in with_ctx)


def test_build_chunk_documents_preserves_display_text():
    files = [
        {"id": "f1", "filename": "a.md", "extracted_text": "hello world",
         "chunks": [{"id": 0, "text": "raw chunk body"}]}
    ]
    docs = build_chunk_documents(files, contextual=True)
    assert docs[0]["text"] == "raw chunk body"
    assert "a.md" in docs[0]["search_text"]


def test_build_chunk_documents_passes_through_stored_embeddings():
    """Stored embeddings must flow from chunk records into the document dict."""
    files = [
        {"id": "f1", "filename": "a.md", "extracted_text": "hello",
         "chunks": [{"id": 0, "text": "body", "embedding": [0.1, 0.2, 0.3]}]}
    ]
    docs = build_chunk_documents(files)
    assert "embedding" in docs[0]
    assert docs[0]["embedding"] == [0.1, 0.2, 0.3]


def test_build_chunk_documents_no_embedding_key_when_absent():
    """Chunks without stored embeddings must not inject an 'embedding' key."""
    files = [
        {"id": "f1", "filename": "a.md", "extracted_text": "hello",
         "chunks": [{"id": 0, "text": "body"}]}
    ]
    docs = build_chunk_documents(files)
    assert "embedding" not in docs[0]


def test_build_chunk_documents_passes_embedding_model_metadata():
    """embedding_model metadata must flow through so retrieval can skip stale vectors."""
    files = [
        {"id": "f1", "filename": "a.md", "extracted_text": "hello",
         "chunks": [{"id": 0, "text": "body", "embedding": [0.1], "embedding_model": "nomic-embed-text"}]}
    ]
    docs = build_chunk_documents(files)
    assert docs[0].get("embedding_model") == "nomic-embed-text"


# ── Integration: repo.search_chunks contract ────────────────────────────────

def test_repo_search_chunks_preserves_shape_and_improves_ranking():
    import asyncio
    from app.db.repositories import repo

    project = asyncio.run(repo.create_project("hybrid-search-test", "rag"))
    pid = project["id"]
    chunks = [
        {"id": 0, "text": "The quarterly revenue report shows strong year over year growth"},
        {"id": 1, "text": "the and or of to in on with as by for"},
        {"id": 2, "text": "Employees enjoyed the summer picnic in the park"},
    ]
    asyncio.run(repo.save_file(
        project_id=pid, filename="report.md", content=b"x",
        extracted_text=" ".join(c["text"] for c in chunks), chunks=chunks,
    ))

    results = asyncio.run(repo.search_chunks(pid, "revenue report", limit=3))
    assert results, "should retrieve at least one chunk"
    assert set(results[0].keys()) == {"file_id", "filename", "chunk_id", "text", "score"}
    assert results[0]["chunk_id"] == 0
    assert results[0]["filename"] == "report.md"
    assert asyncio.run(repo.search_chunks(pid, "", limit=3)) == []


def test_repo_search_chunks_idf_over_naive_overlap():
    """A discriminative rare term must beat a chunk full of repeated common words."""
    import asyncio
    from app.db.repositories import repo

    project = asyncio.run(repo.create_project("hybrid-idf-test", "rag"))
    pid = project["id"]
    chunks = [
        {"id": 0, "text": "general notes about the project and the team and the plan"},
        {"id": 1, "text": "the kubernetes deployment manifest defines three replicas"},
    ]
    asyncio.run(repo.save_file(
        project_id=pid, filename="notes.md", content=b"x",
        extracted_text=" ".join(c["text"] for c in chunks), chunks=chunks,
    ))
    results = asyncio.run(repo.search_chunks(pid, "kubernetes deployment", limit=2))
    assert results[0]["chunk_id"] == 1


def test_engine_phrase_ranking_over_keyword_scatter():
    """Engine must rank the exact-phrase answer above a keyword-scattered distractor.

    This test documents where the lexical engine excels (phrase/proximity signals)
    and what the dense embedding signal would add for true semantic paraphrase.
    """
    docs = [
        {"text": "Error handling: wrap the call in a try/except and log the exception."},
        {"text": "An error log was found while handling the file. Error count handling noted."},
    ]
    results = engine.search("error handling", docs, top_k=2)
    assert results[0].doc["text"].startswith("Error handling:")


def test_lexical_engine_limitation_with_paraphrase():
    """Document the known gap: pure lexical retrieval cannot match paraphrases.

    When query and document share no words, BM25/TF-IDF/rerank cannot help.
    This test proves the gap so it is measurable — enabling RAG_EMBEDDINGS_ENABLED
    with stored chunk vectors is the fix.
    """
    docs = [
        {"text": "Wrap function calls in try/except blocks to handle unexpected exceptions."},
        {"text": "The weather in Paris is sunny in July."},
    ]
    # Query paraphrases the first doc without sharing any content words
    results = engine.search("program crash prevention techniques", docs, top_k=2)
    # Lexical engine likely returns nothing (no shared tokens) — that is the known gap
    for r in results:
        assert r.doc["text"] != "The weather in Paris is sunny in July."  # weather doc must not win


# ── Dense candidate starvation guard ────────────────────────────────────────

def test_dense_top_result_reaches_actual_top_k():
    """Dense top-1 with no lexical overlap must appear in the real top_k=5 results.

    This is the core regression test for weighted RRF.

    The lexical reranker can boost any doc by at most (1 + rerank_weight) = 1.5x.
    For the dense top-1 to reliably beat that:
        dense_rrf_fused_norm > lexical_top1_fused_norm × 1.5
        W / W  >  (2 / W) × 1.5
        1.0    >  3.0 / W
        W      > 3.0

    With dense_rrf_weight=3.0 (the default), a dense top-1 beats any lexical doc
    whose lex_score < 1.0, and ties (winning on tiebreak) with perfect lex_score=1.0.
    This covers the real Zorali use case: top_k=3 in chat, top_k=5 in file analysis.

    Distractors here have PARTIAL lexical overlap (only 1 of 3 query tokens) so
    their lex_score stays well below 1.0 and the semantic doc ranks first.
    """
    # Distractors share only ONE query token ("error") — not the full phrase.
    # This gives them a small but non-zero lexical score (partial match, no exact phrase).
    distractors = [
        {"text": f"general debugging approach for runtime error cases study {i}"}
        for i in range(25)
    ]
    # Semantic-only doc: zero tokens shared with "python error handling"
    semantic_doc = {"text": "reptilian scripts implemented demonstrate catastrophic failure modes"}
    all_docs = distractors + [semantic_doc]
    semantic_idx = len(all_docs) - 1

    eng = HybridSearchEngine(
        rerank=True,
        rerank_weight=0.5,
        candidate_pool=20,
        ranker_guarantee=5,
        rrf_k=60,
        dense_rrf_weight=3.0,
    )
    # Dense-only: semantic doc is the best semantic match (no lexical overlap with query)
    dense_ranking = [(semantic_idx, 1.0)]

    results = eng.search("python error handling", all_docs, top_k=5, extra_rankings=[dense_ranking])
    result_texts = [r.doc["text"] for r in results]
    assert any("reptilian" in t for t in result_texts), (
        "Dense top-1 must reach top_k=5 with dense_rrf_weight=3.0 "
        "(W > 2 × max_lexical_boost ensures semantic beats partial-match lexical docs)"
    )


def test_dense_top_result_survives_candidate_pool_without_weight():
    """ranker_guarantee ensures the dense top-1 is not cut off from the candidate pool.

    Even without dense_rrf_weight boosting the final rank, the protected doc must at
    least appear somewhere in the result set. This test uses top_k=all to verify pool
    survival independently of final ranking.
    """
    distractors = [
        {"text": f"python error handling try except block example number {i}"}
        for i in range(25)
    ]
    semantic_doc = {"text": "reptilian scripts implemented demonstrate catastrophic failure modes"}
    all_docs = distractors + [semantic_doc]
    semantic_idx = len(all_docs) - 1

    eng = HybridSearchEngine(
        rerank=True, rerank_weight=0.5, candidate_pool=20,
        ranker_guarantee=5, rrf_k=60, dense_rrf_weight=1.0,  # no weight boost
    )
    dense_ranking = [(semantic_idx, 1.0)] + [(i, 1.0 / (i + 2)) for i in range(5)]

    results = eng.search(
        "python error handling", all_docs, top_k=len(all_docs),
        extra_rankings=[dense_ranking],
    )
    result_texts = [r.doc["text"] for r in results]
    assert any("reptilian" in t for t in result_texts), (
        "Dense top-1 must appear in the pool (even at low rank) via ranker_guarantee"
    )


def test_ranker_guarantee_not_needed_without_dense():
    """When there is no extra_rankings, ranker_guarantee should not affect results."""
    docs = [
        {"text": "alpha beta gamma delta epsilon"},
        {"text": "zeta eta theta iota kappa"},
    ]
    eng_with = HybridSearchEngine(ranker_guarantee=10, candidate_pool=5)
    eng_without = HybridSearchEngine(ranker_guarantee=1, candidate_pool=5)
    r_with = eng_with.search("alpha beta", docs)
    r_without = eng_without.search("alpha beta", docs)
    # Without dense signal, both engines should agree on the lexical winner
    assert r_with[0].doc["text"] == r_without[0].doc["text"]


# ── Embed texts: prefix and batching (mocked Ollama) ────────────────────────

import pytest


@pytest.mark.asyncio
async def test_embed_texts_uses_nomic_document_prefix():
    """Documents must be sent with 'search_document: ' prefix to Ollama."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.memory.embeddings import embed_texts

    captured: list[dict] = []

    async def fake_post(url, *, json=None, **_kwargs):
        captured.append(json or {})
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        n = len((json or {}).get("input", []))
        resp.json.return_value = {"embeddings": [[0.1, 0.2]] * n}
        return resp

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = fake_post

    with patch("app.memory.embeddings.settings") as s, \
            patch("httpx.AsyncClient", return_value=mock_client):
        s.rag_embeddings_enabled = True
        s.ollama_host = "http://localhost:11434"
        s.rag_embedding_model = "nomic-embed-text"
        s.provider_timeout_seconds = 30.0

        result = await embed_texts(["hello world"], task="document")

    assert result is not None
    assert captured, "expected at least one HTTP POST"
    assert captured[0]["input"][0] == "search_document: hello world"


@pytest.mark.asyncio
async def test_embed_texts_uses_nomic_query_prefix():
    """Queries must be sent with 'search_query: ' prefix to Ollama."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.memory.embeddings import embed_texts

    captured: list[dict] = []

    async def fake_post(url, *, json=None, **_kwargs):
        captured.append(json or {})
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        n = len((json or {}).get("input", []))
        resp.json.return_value = {"embeddings": [[0.1, 0.2]] * n}
        return resp

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = fake_post

    with patch("app.memory.embeddings.settings") as s, \
            patch("httpx.AsyncClient", return_value=mock_client):
        s.rag_embeddings_enabled = True
        s.ollama_host = "http://localhost:11434"
        s.rag_embedding_model = "nomic-embed-text"
        s.provider_timeout_seconds = 30.0

        result = await embed_texts(["find relevant documents"], task="query")

    assert result is not None
    assert captured[0]["input"][0] == "search_query: find relevant documents"


@pytest.mark.asyncio
async def test_embed_texts_splits_into_batches_of_32():
    """More than 32 texts must be split into multiple Ollama requests."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.memory.embeddings import embed_texts, EMBED_BATCH_SIZE

    call_count = 0

    async def fake_post(url, *, json=None, **_kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        n = len((json or {}).get("input", []))
        resp.json.return_value = {"embeddings": [[0.0]] * n}
        return resp

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = fake_post

    texts = [f"chunk {i}" for i in range(EMBED_BATCH_SIZE + 1)]  # 33 texts → 2 batches

    with patch("app.memory.embeddings.settings") as s, \
            patch("httpx.AsyncClient", return_value=mock_client):
        s.rag_embeddings_enabled = True
        s.ollama_host = "http://localhost:11434"
        s.rag_embedding_model = "nomic-embed-text"
        s.provider_timeout_seconds = 30.0

        result = await embed_texts(texts, task="document")

    assert result is not None
    assert len(result) == len(texts)
    assert call_count == 2, f"expected 2 batch calls, got {call_count}"


@pytest.mark.asyncio
async def test_embed_texts_returns_none_when_disabled():
    """embed_texts must return None immediately when rag_embeddings_enabled is False."""
    from unittest.mock import patch
    from app.memory.embeddings import embed_texts

    with patch("app.memory.embeddings.settings") as s:
        s.rag_embeddings_enabled = False
        result = await embed_texts(["some text"])

    assert result is None
