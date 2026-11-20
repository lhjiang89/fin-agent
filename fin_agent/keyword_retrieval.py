"""Day 24 keyword baseline over Day 23 filing chunks.

Candidates are narrowed by permission, symbol, and as-of visibility before any
scoring. Ranking uses a deterministic bag-of-terms overlap with corpus IDF.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from fin_agent.filing_chunks import DEFAULT_MANIFEST, ROOT


RETRIEVAL = "keyword_retrieval.v1"
CHUNKS_PATH = ROOT / "fixtures/filings_snapshot/chunks.jsonl"
QUESTIONS_PATH = ROOT / "fixtures/filings_snapshot/questions.json"

_ASCII_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'/’\-]*")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")
_DIGIT_RUN = re.compile(r"\d{2,}")
_CJK_QUERY_MARKERS = (
    "截至",
    "止年度",
    "止六个月",
    "十二月三十一日",
    "六月三十日",
    "收入",
    "股息",
    "末期股息",
    "微信",
    "活跃",
    "活跃账户",
    "娱乐集团",
    "腾讯控股",
    "腾讯音乐",
    "合併",
    "合并",
    "WeChat",
    "Revenues",
    "Revenue",
)

# Lightweight stop terms for query expansion only (not removed from chunk text).
_QUERY_STOP = frozenset(
    {
        "的", "是", "多少", "截至", "止", "年度", "六个月", "三個月", "及", "和", "在",
        "the", "of", "for", "a", "an", "to", "is", "are", "what", "how",
    }
)

_SYMBOL_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"腾讯音乐|TME|01698|騰訊音樂"), "HK.01698"),
    (re.compile(r"腾讯控股|腾讯|Tencent|00700|騰訊控股|WeChat|Weixin|微信"), "HK.00700"),
]


@dataclass
class SearchFilters:
    as_of: str
    symbol: str | None = None
    allowed_symbols: frozenset[str] | None = None
    document_id: str | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "symbol": self.symbol,
            "allowed_symbols": sorted(self.allowed_symbols) if self.allowed_symbols else None,
            "document_id": self.document_id,
        }


@dataclass
class RankedChunk:
    chunk_id: str
    score: float
    matched_terms: list[str]
    page: int
    anchor: str
    document_id: str
    symbol: str
    kind: str
    rank_reason: str
    chunk: dict[str, Any] = field(repr=False)


def load_chunks(path: Path = CHUNKS_PATH) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_manifest_documents(path: Path = DEFAULT_MANIFEST) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {row["id"]: row for row in payload["documents"]}


def infer_symbol(question: str, document_id: str | None, documents: dict[str, dict[str, Any]]) -> str | None:
    if document_id and document_id in documents:
        return documents[document_id]["symbol"]
    for pattern, symbol in _SYMBOL_RULES:
        if pattern.search(question):
            return symbol
    return None


def _normalize_ascii(word: str) -> str:
    return word.lower().strip("'-’")


def _expand_cjk_span(span: str) -> list[str]:
    terms: list[str] = []
    if 2 <= len(span) <= 20:
        terms.append(span)
    for marker in _CJK_QUERY_MARKERS:
        if marker in span:
            terms.append(marker)
            for piece in span.split(marker):
                if 2 <= len(piece) <= 24:
                    terms.append(piece)
    return terms


def tokenize_for_index(text: str) -> list[str]:
    terms: list[str] = []
    for match in _ASCII_WORD.finditer(text):
        word = _normalize_ascii(match.group(0))
        if len(word) >= 2 and word not in _QUERY_STOP:
            terms.append(word)
    normalized = text.replace("\n", " ").replace("|", " ")
    for match in _CJK_RUN.finditer(normalized):
        terms.extend(_expand_cjk_span(match.group(0)))
    for match in _DIGIT_RUN.finditer(text):
        terms.append(match.group(0))
    return terms


def query_terms(question: str) -> list[str]:
    terms: list[str] = []
    for match in _ASCII_WORD.finditer(question):
        word = _normalize_ascii(match.group(0))
        if len(word) >= 2 and word not in _QUERY_STOP:
            terms.append(word)
    for match in _CJK_RUN.finditer(question):
        terms.extend(_expand_cjk_span(match.group(0)))
    for match in _DIGIT_RUN.finditer(question):
        terms.append(match.group(0))
    # Keep order, drop duplicates and ultra-short noise.
    seen: set[str] = set()
    ordered: list[str] = []
    for term in terms:
        if len(term) < 2 or term in _QUERY_STOP:
            continue
        if term not in seen:
            seen.add(term)
            ordered.append(term)
    return ordered


def searchable_text(chunk: dict[str, Any], documents: dict[str, dict[str, Any]] | None = None) -> str:
    parts = [chunk.get("text", "")]
    for heading in chunk.get("section_headings", []):
        if heading.get("text"):
            parts.append(heading["text"])
    period = chunk.get("period") or {}
    for label in period.get("labels", []):
        parts.append(label)
    issuer = chunk.get("issuer") or {}
    if issuer.get("name"):
        parts.append(issuer["name"])
    snapshot = chunk.get("document") or {}
    if snapshot.get("snapshot_reporting_period"):
        parts.append(snapshot["snapshot_reporting_period"])
    if documents is not None:
        meta = documents.get(chunk["document_id"], {})
        for key in ("company", "title_zh", "title_en", "reporting_period"):
            value = meta.get(key)
            if value:
                parts.append(value)
    return "\n".join(part for part in parts if part)


def _document_visible(document: dict[str, Any], as_of: str) -> bool:
    return document["available_at"] <= as_of


def filter_chunks(
    chunks: Iterable[dict[str, Any]],
    documents: dict[str, dict[str, Any]],
    filters: SearchFilters,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    stats = {
        "input_chunks": 0,
        "rejected_permission": 0,
        "rejected_symbol": 0,
        "rejected_document_id": 0,
        "rejected_as_of": 0,
        "kept": 0,
    }
    for chunk in chunks:
        stats["input_chunks"] += 1
        document = documents[chunk["document_id"]]
        symbol = chunk["issuer"]["symbol"]
        if filters.allowed_symbols is not None and symbol not in filters.allowed_symbols:
            stats["rejected_permission"] += 1
            continue
        if filters.symbol is not None and symbol != filters.symbol:
            stats["rejected_symbol"] += 1
            continue
        if filters.document_id is not None and chunk["document_id"] != filters.document_id:
            stats["rejected_document_id"] += 1
            continue
        if not _document_visible(document, filters.as_of):
            stats["rejected_as_of"] += 1
            continue
        kept.append(chunk)
    stats["kept"] = len(kept)
    return kept, stats


def build_idf(
    chunks: Iterable[dict[str, Any]],
    documents: dict[str, dict[str, Any]] | None = None,
) -> dict[str, float]:
    document_frequency: dict[str, int] = {}
    total = 0
    for chunk in chunks:
        total += 1
        present = set(tokenize_for_index(searchable_text(chunk, documents)))
        for term in present:
            document_frequency[term] = document_frequency.get(term, 0) + 1
    if total == 0:
        return {}
    return {term: math.log((1 + total) / (1 + df)) + 1.0 for term, df in document_frequency.items()}


def _term_hits(term: str, haystack: str) -> int:
    if term.isascii():
        return len(re.findall(re.escape(term), haystack, flags=re.IGNORECASE))
    return haystack.count(term)


def score_chunk(
    question_terms: list[str],
    chunk: dict[str, Any],
    idf: dict[str, float],
    documents: dict[str, dict[str, Any]] | None = None,
) -> tuple[float, list[str]]:
    haystack = searchable_text(chunk, documents)
    score = 0.0
    matched: list[str] = []
    for term in question_terms:
        hits = _term_hits(term, haystack)
        if hits:
            weight = idf.get(term, 1.0)
            score += weight * hits
            matched.append(term)
    return score, matched


def rank_chunks(
    question: str,
    chunks: list[dict[str, Any]],
    idf: dict[str, float],
    *,
    top_k: int = 5,
    documents: dict[str, dict[str, Any]] | None = None,
) -> list[RankedChunk]:
    terms = query_terms(question)
    scored: list[RankedChunk] = []
    for chunk in chunks:
        score, matched = score_chunk(terms, chunk, idf, documents)
        if score <= 0:
            continue
        source = chunk["source"]
        reason = (
            f"matched {len(matched)}/{len(terms)} query terms with weights "
            f"{', '.join(matched) if matched else '(none)'}"
        )
        scored.append(
            RankedChunk(
                chunk_id=chunk["chunk_id"],
                score=round(score, 4),
                matched_terms=matched,
                page=source["page"],
                anchor=source["anchor"],
                document_id=chunk["document_id"],
                symbol=chunk["issuer"]["symbol"],
                kind=chunk["kind"],
                rank_reason=reason,
                chunk=chunk,
            )
        )
    scored.sort(key=lambda row: (-row.score, row.chunk_id))
    return scored[:top_k]


def search_filings_keyword(
    question: str,
    *,
    as_of: str,
    symbol: str | None = None,
    allowed_symbols: Iterable[str] | None = None,
    document_id: str | None = None,
    top_k: int = 5,
    chunks_path: Path = CHUNKS_PATH,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    chunks = load_chunks(chunks_path)
    documents = load_manifest_documents(manifest_path)
    filters = SearchFilters(
        as_of=as_of,
        symbol=symbol,
        allowed_symbols=frozenset(allowed_symbols) if allowed_symbols is not None else None,
        document_id=document_id,
    )
    filtered, filter_stats = filter_chunks(chunks, documents, filters)
    idf = build_idf(filtered, documents)
    ranked = rank_chunks(question, filtered, idf, top_k=top_k, documents=documents)
    return {
        "retrieval": RETRIEVAL,
        "question": question,
        "filters": filters.describe(),
        "filter_stats": filter_stats,
        "query_terms": query_terms(question),
        "candidate_chunks": len(filtered),
        "top_k": top_k,
        "results": [
            {
                "rank": index + 1,
                "chunk_id": row.chunk_id,
                "score": row.score,
                "matched_terms": row.matched_terms,
                "page": row.page,
                "anchor": row.anchor,
                "document_id": row.document_id,
                "symbol": row.symbol,
                "kind": row.kind,
                "rank_reason": row.rank_reason,
                "text_preview": row.chunk["text"][:220].replace("\n", " / "),
            }
            for index, row in enumerate(ranked)
        ],
    }


def precision_recall_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> dict[str, float]:
    top = ranked_ids[:k]
    hits = [chunk_id for chunk_id in top if chunk_id in relevant_ids]
    precision = len(hits) / k if k else 0.0
    recall = len(hits) / len(relevant_ids) if relevant_ids else 0.0
    return {
        "k": k,
        "precision_at_k": precision,
        "recall_at_k": recall,
        "hits_in_top_k": hits,
        "relevant_total": len(relevant_ids),
        "relevant_ids": sorted(relevant_ids),
    }