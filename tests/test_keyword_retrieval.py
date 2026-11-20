import json

import pytest

from fin_agent.keyword_retrieval import (
    QUESTIONS_PATH,
    SearchFilters,
    filter_chunks,
    infer_symbol,
    load_chunks,
    load_manifest_documents,
    precision_recall_at_k,
    search_filings_keyword,
)

AS_OF = "2026-11-19"
ALLOWED = frozenset({"HK.00700", "HK.01698"})


@pytest.fixture()
def chunks():
    return load_chunks()


@pytest.fixture()
def documents():
    return load_manifest_documents()


def _question_by_id(question_id: str) -> dict:
    payload = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    for row in payload["questions"]:
        if row["id"] == question_id:
            return row
    raise KeyError(question_id)


def test_filter_chunks_applies_permission_symbol_and_as_of(chunks, documents):
    filters = SearchFilters(as_of=AS_OF, symbol="HK.01698", allowed_symbols=ALLOWED)
    kept, stats = filter_chunks(chunks, documents, filters)
    assert stats["input_chunks"] == 772
    assert stats["rejected_symbol"] == 676
    assert stats["kept"] == 96
    assert all(row["issuer"]["symbol"] == "HK.01698" for row in kept)
    assert all(documents[row["document_id"]]["available_at"] <= AS_OF for row in kept)


def test_filter_rejects_future_documents(chunks, documents):
    filters = SearchFilters(as_of="2020-01-01", symbol="HK.00700", allowed_symbols=ALLOWED)
    kept, stats = filter_chunks(chunks, documents, filters)
    assert kept == []
    assert stats["rejected_symbol"] == 96
    assert stats["rejected_as_of"] == 676


def test_q5_top5_stays_on_tme_and_excludes_tencent_751766(chunks, documents):
    item = _question_by_id("D22-Q5")
    symbol = infer_symbol(item["question"], item.get("document_id"), documents)
    result = search_filings_keyword(
        item["question"],
        as_of=AS_OF,
        symbol=symbol,
        allowed_symbols=ALLOWED,
    )
    assert result["candidate_chunks"] == 96
    for row in result["results"]:
        assert row["symbol"] == "HK.01698"
        assert "751,766" not in row["text_preview"]
        assert row["document_id"] == "tme_hk01698_2025_annual_results"


def test_q2_evidence_chunk_is_in_top5(documents):
    item = _question_by_id("D22-Q2")
    symbol = infer_symbol(item["question"], item.get("document_id"), documents)
    result = search_filings_keyword(
        item["question"],
        as_of=AS_OF,
        symbol=symbol,
        allowed_symbols=ALLOWED,
    )
    ids = [row["chunk_id"] for row in result["results"]]
    assert "tencent_hk00700_2025_annual_results:p003:c001" in ids


def test_keyword_search_is_deterministic(documents):
    item = _question_by_id("D22-Q1")
    symbol = infer_symbol(item["question"], item.get("document_id"), documents)
    kwargs = dict(
        question=item["question"],
        as_of=AS_OF,
        symbol=symbol,
        allowed_symbols=ALLOWED,
    )
    first = search_filings_keyword(**kwargs)
    second = search_filings_keyword(**kwargs)
    assert first["results"] == second["results"]


def test_precision_recall_at_k_helper():
    metrics = precision_recall_at_k(
        ["a", "b", "c", "d", "e"],
        {"b", "z"},
        5,
    )
    assert metrics["precision_at_k"] == pytest.approx(0.2)
    assert metrics["recall_at_k"] == pytest.approx(0.5)
    assert metrics["hits_in_top_k"] == ["b"]


def test_q1_strict_gold_misses_top5(documents):
    item = _question_by_id("D22-Q1")
    symbol = infer_symbol(item["question"], item.get("document_id"), documents)
    result = search_filings_keyword(
        item["question"],
        as_of=AS_OF,
        symbol=symbol,
        allowed_symbols=ALLOWED,
    )
    ranked = [row["chunk_id"] for row in result["results"]]
    gold = {"tencent_hk00700_2025_annual_results:p002:c001"}
    metrics = precision_recall_at_k(ranked, gold, 5)
    assert metrics["precision_at_k"] == 0.0
    assert metrics["recall_at_k"] == 0.0