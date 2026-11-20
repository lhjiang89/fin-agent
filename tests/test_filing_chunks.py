import hashlib
import json
import re

import pytest

from fin_agent.filing_chunks import (
    ROOT,
    Line,
    _table_spans,
    build_filing_chunks,
    build_profile,
    classify_lines,
    extract_lines,
    load_manifest_documents,
    write_jsonl,
)

CHUNKS_PATH = ROOT / "fixtures/filings_snapshot/chunks.jsonl"
QUESTIONS_PATH = ROOT / "fixtures/filings_snapshot/questions.json"


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text.replace(" | ", ""))


def _chunks():
    return build_filing_chunks()


def test_table_span_keeps_unit_line_and_does_not_absorb_the_next_paragraph():
    def line(y, text, cells, kind, size=10.0, x1=220.0):
        return Line(
            page=1, y0=y, y1=y + 8, x0=70, x1=x1, size=size, bold_ratio=0.0,
            cells=cells, text=text, kind=kind, page_width=600, page_height=840,
        )

    lines = [
        line(10, "截至十二月三十一日止年度", ["截至十二月三十一日止年度"], "caption"),
        line(24, "（人民幣百萬元，另有指明者除外）", ["（人民幣百萬元，另有指明者除外）"], "unit"),
        line(40, "收入 | 751,766 | 660,257", ["收入", "751,766", "660,257"], "table_row", x1=520),
        line(120, "股息", ["股息"], "heading", size=14),
        line(150, "每股5.30港元。", ["每股5.30港元。"], "prose", x1=520),
    ]
    assert _table_spans(lines) == [(0, 2)]


def test_manifest_hash_mismatch_is_refused():
    raw = json.loads(json.dumps(load_manifest_documents()[0]))
    raw["download"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="sha256"):
        build_profile(raw, ROOT)


def test_chunks_are_deterministic_and_match_the_committed_jsonl(tmp_path):
    first = _chunks()
    second = _chunks()
    assert first == second
    target = tmp_path / "chunks.jsonl"
    write_jsonl(first, target)
    assert target.read_bytes() == CHUNKS_PATH.read_bytes()


def test_every_chunk_stays_inside_one_document_and_names_its_issuer():
    chunks = _chunks()
    documents = {item["id"]: item for item in load_manifest_documents()}
    assert set(documents) == {
        "tencent_hk00700_2025_annual_results",
        "tencent_hk00700_2026_interim_results",
        "tme_hk01698_2025_annual_results",
    }
    seen = {document_id: set() for document_id in documents}
    for chunk in chunks:
        document = documents[chunk["document_id"]]
        seen[chunk["document_id"]].add(chunk["source"]["page"])
        assert chunk["chunk_id"].startswith(chunk["document_id"] + ":")
        assert 1 <= chunk["source"]["page"] <= document["download"]["pages"]
        assert chunk["source"]["sha256"] == document["download"]["sha256"]
        assert chunk["issuer"]["symbol"] == document["symbol"]
        assert chunk["issuer"]["symbol_source"].endswith("manifest.json")
        assert chunk["text"].strip()
        if chunk["kind"] == "table":
            assert chunk["column_separator"] == " | "
        else:
            assert chunk["column_separator"] is None
        quote = chunk["period"]["evidence_quote"]
        if chunk["period"]["evidence_kind"] == "in_chunk":
            assert quote in chunk["text"]
        unit = chunk["unit"]
        if unit and unit["evidence_kind"] == "in_chunk":
            assert unit["evidence_quote"] in chunk["text"]
        if chunk["document_id"].startswith("tme_"):
            assert chunk["issuer"]["name"] == "騰訊音樂娛樂集團"
            assert "騰訊控股有限公司" not in chunk["issuer"]["name"]
        else:
            assert "騰訊控股有限公司" in chunk["issuer"]["name"] or chunk["issuer"]["name"].startswith("Tencent Holdings Limited")
            assert not chunk["issuer"]["name"].startswith("騰訊音樂")
    for document_id, document in documents.items():
        assert seen[document_id] == set(range(1, document["download"]["pages"] + 1))


def test_company_evidence_comes_from_the_pdf_not_from_another_filing():
    chunks = _chunks()
    annual = next(chunk for chunk in chunks if chunk["document_id"] == "tencent_hk00700_2025_annual_results")
    interim = next(chunk for chunk in chunks if chunk["document_id"] == "tencent_hk00700_2026_interim_results")
    music = next(chunk for chunk in chunks if chunk["document_id"] == "tme_hk01698_2025_annual_results")
    assert annual["issuer"]["name_evidence"]["page"] == 55
    assert "騰訊控股有限公司" in annual["issuer"]["name_evidence"]["quote"]
    assert annual["issuer"]["stock_codes"][0]["page"] == 1
    assert "700" in annual["issuer"]["stock_codes"][0]["quote"]
    assert interim["issuer"]["name_evidence"]["page"] == 47
    assert interim["issuer"]["name_evidence"]["quote"].startswith("Tencent Holdings Limited")
    assert "1698" in music["issuer"]["stock_codes"][0]["quote"]
    assert music["issuer"]["stock_codes"][1]["quote"] == "紐交所股份代號：TME"


def test_numbers_from_different_filings_are_not_mixed():
    chunks = _chunks()
    for needle, document_id in (
        ("751,766", "tencent_hk00700_2025_annual_results"),
        ("401,243", "tencent_hk00700_2026_interim_results"),
        ("32,902", "tme_hk01698_2025_annual_results"),
    ):
        found = {chunk["document_id"] for chunk in chunks if needle in chunk["text"]}
        assert found == {document_id}


def test_day22_question_evidence_is_still_in_the_chunks():
    chunks = _chunks()
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))["questions"]

    def hits(question, needle):
        squashed = _squash(needle)
        return [
            chunk for chunk in chunks
            if chunk["document_id"] == question["document_id"] and squashed in _squash(chunk["text"])
        ]

    by_id = {question["id"]: question for question in questions}
    q1 = hits(by_id["D22-Q1"], by_id["D22-Q1"]["quote"])
    assert any(chunk["source"]["page"] == 2 and "（人民幣百萬元，另有指明者除外）" in chunk["text"] for chunk in q1)
    q2 = hits(by_id["D22-Q2"], by_id["D22-Q2"]["quote"])
    assert [chunk["source"]["page"] for chunk in q2] == [3]
    assert q2[0]["unit"]["currency"] == "港元"
    q3 = hits(by_id["D22-Q3"], by_id["D22-Q3"]["quote"])
    assert any(chunk["source"]["page"] == 2 and "(RMB in millions, unless specified)" in chunk["text"] for chunk in q3)
    q4 = hits(by_id["D22-Q4"], by_id["D22-Q4"]["quote"])
    assert len(q4) == 1 and q4[0]["source"]["page"] == 3
    assert q4[0]["unit"]["raw"] == "(in millions, unless specified)"
    assert q4[0]["unit"]["currency"] is None
    highlight = hits(by_id["D22-Q5"], by_id["D22-Q5"]["quote_highlight"])
    statement = [
        chunk for chunk in chunks
        if chunk["document_id"].startswith("tme_") and "32,902" in chunk["text"] and "26,726" in chunk["text"]
    ]
    assert [chunk["source"]["page"] for chunk in highlight] == [3]
    assert [chunk["source"]["page"] for chunk in statement] == [13]
    assert highlight[0]["chunk_id"] != statement[0]["chunk_id"]
    assert "4,705" in statement[0]["text"] and "6,176" in statement[0]["text"]
    profit = [chunk for chunk in chunks if chunk["document_id"].startswith("tme_") and "11,056" in chunk["text"]]
    assert [chunk["source"]["page"] for chunk in profit] == [14]


def test_body_lines_are_covered_and_page_number_footers_are_not_chunks():
    chunks = _chunks()
    text_by_page = {}
    for chunk in chunks:
        text_by_page.setdefault((chunk["document_id"], chunk["source"]["page"]), []).append(chunk["text"])
        assert chunk["text"].strip() != str(chunk["source"]["page"])
    for raw in load_manifest_documents():
        lines = classify_lines(extract_lines(ROOT / raw["download"]["path"]))
        footers = [line for line in lines if line.kind == "furniture"]
        assert len(footers) == raw["download"]["pages"]
        for line in lines:
            if line.kind == "furniture":
                continue
            blob = "\n".join(text_by_page[(raw["id"], line.page)])
            if line.text in blob:
                continue
            parts = [part.strip() for part in re.split(r"(?<=[。！？])|(?<=\.)\s+", line.text) if part.strip()]
            assert len(parts) > 1 and all(part in blob for part in parts), (raw["id"], line.page, line.text)


def test_day22_snapshot_files_are_unchanged():
    expected = {
        "fixtures/filings.json": "77e02866566b0c90a3bebb7c11af16b28af26542422abbd266013a44ab013756",
        "fixtures/filings_snapshot/manifest.json": "0b1166cbfbaba81bd90703c67c9459cd2b8a29286062b6adde11997ee255a641",
        "fixtures/filings_snapshot/questions.json": "60b1d287dcebbbfe2b1617ef8da52fa2290edb313cf733ebd071244807457242",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
