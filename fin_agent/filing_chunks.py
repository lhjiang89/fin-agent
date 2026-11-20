"""Chunk the Day 22 filing PDFs into retrieval blocks.

Tables stay with their headers, unit line, and period line. Paragraphs break
on headings, bullets, and vertical gaps. Text is the extracted wording;
company, period, and unit taken from elsewhere in the same PDF are stored
beside it with the page and quote they came from.

The column marker `` | `` is inserted where a horizontal gap separates
cells. It is not a character in the PDF.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


CHUNKER = "filing_chunks.v1"
COLUMN_GAP = 6.0
Y_TOLERANCE = 3.0
COLUMN_SEPARATOR = " | "

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "fixtures/filings_snapshot/manifest.json"

_AMOUNT_RE = re.compile(r"^[（(]?-?\d[\d,]*(?:\.\d+)?%?[)）]?$")
_PERIOD_RES = [
    re.compile(r"截至[零〇○一二三四五六七八九十]{2,8}年[零〇○一二三四五六七八九十]{1,4}月[零〇○一二三四五六七八九十]{1,4}日止(?:年度|三個月|六個月|三個月及六個月|三個月及全年)"),
    re.compile(r"截至[零〇○一二三四五六七八九十]{2,8}年[零〇○一二三四五六七八九十]{1,4}月[零〇○一二三四五六七八九十]{1,4}日"),
    re.compile(r"於[零〇○一二三四五六七八九十]{2,8}年[零〇○一二三四五六七八九十]{1,4}月[零〇○一二三四五六七八九十]{1,4}日"),
    re.compile(r"截至十二月三十一日止年度"),
    re.compile(r"截至下列日期止三個月"),
    re.compile(r"截至\s*12\s*月\s*31\s*日止(?:三個月|年度)"),
    re.compile(r"截至\s*20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日止(?:三個月及全年|三個月|六個月|年度|全年)"),
    re.compile(r"2\s*0\s*2\s*5\s*年第四季度"),
    re.compile(r"20\d{2}年全年"),
    re.compile(r"20\d{2}年第四季度"),
    re.compile(r"(?i)for the three and six months ended \d{1,2} [A-Za-z]+ \d{4}"),
    re.compile(r"(?i)(?:three|six) months ended(?: \d{1,2} [A-Za-z]+ \d{4})?"),
    re.compile(r"(?i)year ended \d{1,2} [A-Za-z]+ \d{4}"),
    re.compile(r"(?i)as at \d{1,2} [A-Za-z]+ \d{4}"),
]
_YEAR_CELL_RE = re.compile(
    r"^(?:於)?(?:20\d{2}|[零〇○一二三四五六七八九十]{4}年)$|^(?:十二月|六月|九月|三月)[零〇○一二三四五六七八九十]{1,4}日$|^(?:30 June|31 December|31 March|30 September)$"
)
_UNIT_SPECS = [
    ("（人民幣百萬元，另有指明者除外）", "人民幣", "百萬元"),
    ("(RMB in millions, unless specified)", "RMB", "millions"),
    ("（百萬計，另有指明者除外）", None, "百萬（計數）"),
    ("(in millions, unless specified)", None, "millions"),
    ("（百萬元，每股數據除外）", None, "百萬元"),
    ("（百萬元）", None, "百萬元"),
    ("人民幣百萬元", "人民幣", "百萬元"),
    ("RMB’Million", "RMB", "million"),
    ("RMB'Million", "RMB", "million"),
]
_ISSUER_RES = [
    re.compile(r"騰訊控股有限公司，一間根據開曼群島法律組織\s*及存續的有限責任公司，其股份於聯交所上市"),
    re.compile(
        r"Tencent Holdings Limited, a limited liability company organised and existing under the laws of the Cayman Islands and the shares of which are listed on the Stock Exchange"
    ),
]
_STOCK_RES = [
    re.compile(r"股份代號：700（港幣櫃台）及80700（人民幣櫃台）"),
    re.compile(r"Stock Codes: 700 \(HKD counter\) and 80700 \(RMB counter\)"),
    re.compile(r"港交所股份代號：1698"),
    re.compile(r"紐交所股份代號：TME"),
]


@dataclass
class Line:
    page: int
    y0: float
    y1: float
    x0: float
    x1: float
    size: float
    bold_ratio: float
    cells: list[str]
    text: str
    kind: str = ""
    page_width: float = 0.0
    page_height: float = 0.0


@dataclass
class DocumentProfile:
    raw: dict[str, Any]
    pdf_path: Path
    sha256: str
    pages: int
    issuer_name: str
    issuer_evidence: dict[str, Any]
    stock_codes: list[dict[str, Any]]
    title_quote: str
    title_page: int
    title_periods: list[str]

    @property
    def document_id(self) -> str:
        return self.raw["id"]

    @property
    def symbol(self) -> str:
        return self.raw["symbol"]

    @property
    def language(self) -> str:
        return self.raw["language"]

    @property
    def snapshot_reporting_period(self) -> str:
        return self.raw["reporting_period"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest_documents(manifest_path: Path = DEFAULT_MANIFEST) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = manifest.get("documents")
    if not documents:
        raise ValueError(f"{manifest_path} has no documents")
    return documents


def _needs_space(left: str, right: str) -> bool:
    if not left or not right:
        return False
    end, start = left[-1], right[0]
    return end.isascii() and start.isascii() and (end.isalnum() or start.isalnum())


def _join_cell(spans: list[Any]) -> str:
    text = ""
    previous_x1 = None
    for span in spans:
        gap = None if previous_x1 is None else span["bbox"][0] - previous_x1
        piece = span["text"]
        if gap is not None and gap > 0.8 and text and not text.endswith(" ") and not piece.startswith(" "):
            if _needs_space(text, piece):
                text += " "
        text += piece
        previous_x1 = span["bbox"][2]
    return re.sub(r"\s+", " ", text).strip()


def _is_bold(span: dict[str, Any]) -> bool:
    return bool(span["flags"] & 16) or "Bold" in span["font"]


def _fitz():
    try:
        import fitz
    except ImportError as exc:
        raise ImportError("filing chunks need pymupdf==1.26.5") from exc
    return fitz


def extract_lines(pdf_path: Path) -> list[Line]:
    fitz = _fitz()
    document = fitz.open(pdf_path)
    lines: list[Line] = []
    try:
        for page_index, page in enumerate(document, start=1):
            spans: list[dict[str, Any]] = []
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for raw_line in block["lines"]:
                    for span in raw_line["spans"]:
                        if span["text"].strip():
                            spans.append(span)
            spans.sort(key=lambda span: (span["bbox"][1], span["bbox"][0]))
            rows: list[dict[str, Any]] = []
            for span in spans:
                y0 = span["bbox"][1]
                chosen = None
                best = Y_TOLERANCE + 1
                for row in rows:
                    delta = abs(row["y_ref"] - y0)
                    if delta <= Y_TOLERANCE and delta < best:
                        chosen = row
                        best = delta
                if chosen is None:
                    rows.append({"y_ref": y0, "spans": [span]})
                else:
                    chosen["spans"].append(span)
            for row in rows:
                row_spans = sorted(row["spans"], key=lambda span: span["bbox"][0])
                cells: list[list[dict[str, Any]]] = [[]]
                previous_x1 = None
                for span in row_spans:
                    if previous_x1 is not None and span["bbox"][0] - previous_x1 > COLUMN_GAP:
                        cells.append([])
                    cells[-1].append(span)
                    previous_x1 = span["bbox"][2]
                rendered = [_join_cell(group) for group in cells]
                rendered = [cell for cell in rendered if cell]
                if not rendered:
                    continue
                bold_chars = 0
                total_chars = 0
                sizes: list[float] = []
                for span in row_spans:
                    count = len(span["text"].strip())
                    total_chars += count
                    sizes.extend([span["size"]] * max(count, 1))
                    if _is_bold(span):
                        bold_chars += count
                size = sorted(sizes)[len(sizes) // 2]
                lines.append(
                    Line(
                        page=page_index,
                        y0=min(span["bbox"][1] for span in row_spans),
                        y1=max(span["bbox"][3] for span in row_spans),
                        x0=min(span["bbox"][0] for span in row_spans),
                        x1=max(span["bbox"][2] for span in row_spans),
                        size=round(size, 1),
                        bold_ratio=(bold_chars / total_chars) if total_chars else 0.0,
                        cells=rendered,
                        text=" | ".join(rendered),
                        page_width=page.rect.width,
                        page_height=page.rect.height,
                    )
                )
    finally:
        document.close()
    return lines


def _is_numeric_token(cell: str) -> bool:
    return bool(_AMOUNT_RE.fullmatch(cell.strip()))


def _is_year_token(cell: str) -> bool:
    return bool(re.fullmatch(r"20\d{2}", cell.strip()))


def _is_small_note(cell: str) -> bool:
    return bool(re.fullmatch(r"\d{1,2}", cell.strip()))


def _is_header_cell(cell: str) -> bool:
    text = cell.strip()
    if re.fullmatch(r"(?:於)?[零〇○一二三四五六七八九十]{4}年", text):
        return True
    if re.fullmatch(r"(?:十二月|十一月|十月|九月|八月|七月|六月|五月|四月|三月|二月|一月)[零〇○一二三四五六七八九十]{0,4}日?", text):
        return True
    return text in {"同比變動", "環比變動", "未經審核", "未經審計", "Year-on-year", "Quarter-on-quarter"}


def _looks_like_caption(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 80:
        return False
    if stripped in {"未經審核", "未經審計", "Unaudited"}:
        return True
    if stripped.startswith(("未經審核", "未經審計", "Unaudited ")) and ("截至" in stripped or "ended" in stripped.lower()):
        return True
    if re.match(r"^截至.{0,40}止", stripped):
        return True
    if re.match(r"(?i)^(six months ended|three months ended|as at|year ended|for the .+ended)", stripped):
        return True
    return False


def _is_page_number(line: Line) -> bool:
    if line.text.strip() != str(line.page):
        return False
    if line.y0 < line.page_height * 0.88:
        return False
    center = (line.x0 + line.x1) / 2
    return abs(center - line.page_width / 2) < 40


def classify_line(line: Line) -> str:
    if _is_page_number(line):
        return "furniture"
    numeric = [cell for cell in line.cells if _is_numeric_token(cell) and not _is_year_token(cell)]
    value_nums = [cell for cell in numeric if not _is_small_note(cell)]
    if value_nums and len(line.cells) >= 2:
        return "table_row"
    if len(line.cells) >= 2 and not any(mark in line.text for mark in ("。", "，")) and all(len(cell) <= 28 for cell in line.cells):
        if all(_is_year_token(cell) or _is_header_cell(cell) for cell in line.cells):
            return "table_header"
        if sum(_is_header_cell(cell) for cell in line.cells) >= 2:
            return "table_header"
        header_tokens = ("同比", "環比", "變動", "人民幣", "美元", "百萬", "附註", "RMB", "change", "June", "March", "December", "Note", "Year", "Quarter", "Unaudited", "months")
        if not numeric and any(any(token in cell for token in header_tokens) for cell in line.cells):
            return "table_header"
        if len(line.cells) >= 3 and all(len(cell) <= 16 for cell in line.cells):
            return "table_header"
    if (
        line.bold_ratio >= 0.6
        and line.size >= 11.5
        and len(line.text) <= 60
        and not line.text.endswith(("。", "."))
        and len(line.cells) == 1
    ):
        return "heading"
    if _looks_like_caption(line.text):
        return "caption"
    if any(token in line.text for token in ("（人民幣百萬元", "(RMB in millions", "（百萬計", "(in millions", "（百萬元，每股", "人民幣百萬元", "RMB’Million", "RMB'Million")):
        if len(line.text) <= 40:
            return "unit"
    return "prose"


def classify_lines(lines: list[Line]) -> list[Line]:
    for line in lines:
        line.kind = classify_line(line)
        line.text = _render_line(line)
    return lines


def _render_line(line: Line) -> str:
    if line.kind in {"table_row", "table_header"}:
        return COLUMN_SEPARATOR.join(line.cells)
    if len(line.cells) == 2 and line.cells[0] in {"‧", "•", "·", "#", "＃"}:
        return f"{line.cells[0]} {line.cells[1]}"
    if len(line.cells) == 1:
        return line.cells[0]
    return " ".join(line.cells)


def _is_short_label(line: Line) -> bool:
    if line.kind not in {"prose", "heading"} or line.size >= 13.5:
        return False
    # A full-width line is wrapped prose. Row labels leave the number columns empty.
    if line.x1 - line.x0 > 320:
        return False
    text = line.text.strip()
    if not text or len(text) > 60 or text.endswith(("。", ".")):
        return False
    if "下表" in text or "The following" in text or "sets out" in text.lower():
        return False
    return True


def _bridge_to_row(lines: list[Line], start: int, origin_y: float) -> int:
    """Index of a nearby table row reached through a few short label lines."""
    if start >= len(lines) or _is_new_table_caption(lines[start]):
        return -1
    page = lines[start].page
    hops = 0
    index = start
    while index < len(lines) and lines[index].page == page and hops <= 2:
        if lines[index].y0 - origin_y > 64:
            return -1
        kind = lines[index].kind
        if kind == "table_row":
            return index
        if _is_new_table_caption(lines[index]):
            return -1
        if kind in {"table_header", "unit", "caption"} or _is_short_label(lines[index]):
            index += 1
            hops += 1
            continue
        return -1
    return -1


def _is_new_table_caption(line: Line) -> bool:
    text = line.text.strip()
    if "未經審核" in text or "未經審計" in text or "Unaudited" in text:
        return True
    if re.search(r"截至.+止", text) and len(text) <= 40:
        return True
    return bool(re.search(r"(?i)(three|six) months ended|as at", text)) and len(text) <= 80


def _table_spans(lines: list[Line]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(lines):
        if lines[index].kind != "table_row":
            index += 1
            continue
        start = index
        label_budget = 6
        while start > 0 and lines[start - 1].page == lines[index].page:
            previous = lines[start - 1]
            if previous.kind == "table_row":
                break
            if previous.kind in {"table_header", "unit", "caption", "heading"}:
                start -= 1
                label_budget = 6
                continue
            if label_budget and _is_short_label(previous) and lines[start].y0 - previous.y0 <= 36:
                start -= 1
                label_budget -= 1
                continue
            break
        end = index
        while end + 1 < len(lines) and lines[end + 1].page == lines[start].page:
            nxt = lines[end + 1]
            if nxt.kind in {"table_row", "table_header", "unit", "caption"} and not _is_new_table_caption(nxt):
                end += 1
                continue
            bridged = _bridge_to_row(lines, end + 1, lines[end].y0)
            if bridged > end:
                end = bridged
                continue
            break
        spans.extend(_split_table_span(lines, start, end))
        index = end + 1
    return _merge_touching_spans(spans)


def _split_table_span(lines: list[Line], start: int, end: int) -> list[tuple[int, int]]:
    cuts = [start]
    seen_row = False
    for index in range(start + 1, end + 1):
        gap = lines[index].y0 - lines[index - 1].y0
        if seen_row and gap > 20 and _is_new_table_caption(lines[index]):
            if any(lines[later].kind == "table_row" for later in range(index, end + 1)):
                cuts.append(index)
                seen_row = False
        if lines[index].kind == "table_row":
            seen_row = True
    cuts.append(end + 1)
    return [(cuts[pos], cuts[pos + 1] - 1) for pos in range(len(cuts) - 1)]


def _merge_touching_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _same_paragraph(previous: Line, nxt: Line) -> bool:
    if previous.page != nxt.page:
        return False
    if nxt.text.strip().startswith(("‧", "•", "·")):
        return False
    return nxt.y0 - previous.y0 <= max(previous.size * 2.15, 24)


def _join_paragraph(lines: list[Line], language: str) -> str:
    parts: list[str] = []
    for index, line in enumerate(lines):
        parts.append(line.text.strip())
        if index == len(lines) - 1:
            break
        if line.kind in {"heading", "caption"} or lines[index + 1].kind in {"heading", "caption"}:
            parts.append("\n")
        elif language == "en":
            parts.append(" ")
        else:
            current = parts[-1]
            nxt = lines[index + 1].text.strip()
            if current and nxt and _needs_space(current, nxt):
                parts.append(" ")
    return "".join(parts).strip()


def _split_long_paragraph(text: str, language: str, limit: int = 900) -> list[str]:
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        if language == "en":
            cut = window.rfind(". ")
            cut = cut + 1 if cut >= 200 else -1
        else:
            cut = max(window.rfind("。"), window.rfind("！"), window.rfind("？"))
            cut = cut + 1 if cut >= 200 else -1
        if cut < 0:
            break
        pieces.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        pieces.append(rest)
    return pieces


def period_labels(text: str, extra_cells: Iterable[str] = ()) -> list[str]:
    found: list[str] = []
    for pattern in _PERIOD_RES:
        for match in pattern.finditer(text):
            label = re.sub(r"\s+", " ", match.group(0)).strip()
            if label and label not in found:
                found.append(label)
    for cell in extra_cells:
        cleaned = cell.strip()
        if _YEAR_CELL_RE.fullmatch(cleaned) and cleaned not in found:
            found.append(cleaned)
    return found


def detect_unit(text: str, cells: Iterable[str] = ()) -> Optional[dict[str, Any]]:
    raw = None
    currency = None
    scale = None
    for needle, needle_currency, needle_scale in _UNIT_SPECS:
        if needle in text:
            raw = needle
            currency = needle_currency
            scale = needle_scale
            break
    cell_list = [cell.strip() for cell in cells]
    if raw is None and "港元" in text and "每股" in text:
        match = re.search(r"每股.{0,12}港元", text)
        raw = match.group(0) if match else "港元"
        currency = "港元"
        scale = "每股"
    elif raw is None and ("億元" in text or "億美元" in text):
        match = re.search(r"(?:人民幣|美元).{0,16}億(?:元|美元)|億元|億美元", text)
        raw = match.group(0) if match else ("億元" if "億元" in text else "億美元")
        has_rmb = "人民幣" in text
        has_usd = "美元" in text
        currency = "人民幣及美元" if has_rmb and has_usd else ("美元" if has_usd else "人民幣")
        scale = "億元"
    if raw is None:
        return None
    header_blob = " ".join(cell_list)
    if "人民幣" in header_blob and "美元" in header_blob and scale == "百萬元":
        currency = "人民幣及美元"
    if currency is None and "人民幣" in text and scale == "百萬元":
        currency = "人民幣"
    if currency is None and "美元" in header_blob and scale == "百萬元":
        currency = "美元"
    return {"currency": currency, "scale": scale, "raw": raw}


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _page_texts(pdf_path: Path) -> list[str]:
    fitz = _fitz()
    document = fitz.open(pdf_path)
    try:
        return [_normalize_ws(page.get_text()) for page in document]
    finally:
        document.close()


def _first_match(pages: list[str], pattern: re.Pattern[str]) -> Optional[dict[str, Any]]:
    for index, text in enumerate(pages, start=1):
        match = pattern.search(text)
        if match:
            return {"page": index, "quote": match.group(0), "normalization": "whitespace collapsed to single spaces"}
    return None


def build_profile(raw: dict[str, Any], root: Path) -> DocumentProfile:
    pdf_path = root / raw["download"]["path"]
    expected = raw["download"]["sha256"]
    actual = sha256_file(pdf_path)
    if actual != expected:
        raise ValueError(f"{pdf_path} sha256 {actual} does not match the Day 22 manifest")
    pages = _page_texts(pdf_path)
    if len(pages) != raw["download"]["pages"]:
        raise ValueError(f"{pdf_path} has {len(pages)} pages, manifest says {raw['download']['pages']}")
    if raw["id"].startswith("tme_"):
        issuer = _first_match(pages, re.compile(r"騰訊音樂娛樂集團")) or _first_match(pages, re.compile(r"Tencent Music Entertainment Group"))
    elif raw["language"] == "en":
        issuer = _first_match(pages, _ISSUER_RES[1])
    else:
        issuer = _first_match(pages, _ISSUER_RES[0])
    if issuer is None:
        raise ValueError(f"no issuer evidence in {pdf_path}")
    stock_codes = []
    for pattern in _STOCK_RES:
        found = _first_match(pages, pattern)
        if found:
            stock_codes.append(found)
    if not stock_codes:
        raise ValueError(f"no stock-code evidence in {pdf_path}")
    title_page = pages[0]
    title_periods = period_labels(title_page)
    title_quote = title_page[:280]
    return DocumentProfile(
        raw=raw,
        pdf_path=pdf_path,
        sha256=expected,
        pages=len(pages),
        issuer_name=issuer["quote"],
        issuer_evidence=issuer,
        stock_codes=stock_codes,
        title_quote=title_quote,
        title_page=1,
        title_periods=title_periods,
    )


def _section_entry(line: Line) -> dict[str, Any]:
    return {"text": line.text.strip(), "page": line.page, "size": line.size}


def _push_section(stack: list[dict[str, Any]], line: Line) -> None:
    if line.kind != "heading" or line.size < 11.5:
        return
    while stack and line.size >= stack[-1]["size"] - 0.2:
        stack.pop()
    stack.append(_section_entry(line))


def _bbox(lines: list[Line]) -> list[float]:
    return [
        round(min(line.x0 for line in lines), 1),
        round(min(line.y0 for line in lines), 1),
        round(max(line.x1 for line in lines), 1),
        round(max(line.y1 for line in lines), 1),
    ]


def _issuer_block(profile: DocumentProfile) -> dict[str, Any]:
    return {
        "name": profile.issuer_name,
        "name_evidence": profile.issuer_evidence,
        "stock_codes": profile.stock_codes,
        "symbol": profile.symbol,
        "symbol_source": "fixtures/filings_snapshot/manifest.json",
        "symbol_note": "PDF 印出的是股份代号。symbol 沿用 Day 22 manifest 对同一 sha256 文件的标的，不是把 HK. 前缀写进原文。",
    }


def _period_block(text: str, cells: Iterable[str], section: list[dict[str, Any]], profile: DocumentProfile, page: int) -> dict[str, Any]:
    labels = period_labels(text, cells)
    if labels:
        return {
            "labels": labels,
            "evidence_kind": "in_chunk",
            "evidence_page": page,
            "evidence_quote": labels[0],
        }
    for heading in reversed(section):
        heading_labels = period_labels(heading["text"])
        if heading_labels:
            return {
                "labels": heading_labels,
                "evidence_kind": "section_heading",
                "evidence_page": heading["page"],
                "evidence_quote": heading["text"],
            }
    if profile.title_periods:
        return {
            "labels": profile.title_periods,
            "evidence_kind": "document_title",
            "evidence_page": profile.title_page,
            "evidence_quote": profile.title_periods[0],
        }
    return {
        "labels": [],
        "evidence_kind": "not_found",
        "evidence_page": None,
        "evidence_quote": None,
    }


def _apply_unit(text: str, cells: Iterable[str], page: int, carried: Optional[dict[str, Any]]) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    found = detect_unit(text, cells)
    if found:
        found.update({"evidence_kind": "in_chunk", "evidence_page": page, "evidence_quote": found["raw"]})
        return found, found
    if carried:
        reused = {
            "currency": carried["currency"],
            "scale": carried["scale"],
            "raw": carried["raw"],
            "evidence_kind": "carried_from_previous_table",
            "evidence_page": carried["evidence_page"],
            "evidence_quote": carried["evidence_quote"],
            "note": "本块正文没有单位行。单位沿用同一节、相邻表格块已经出现的单位行，没有写回正文。",
        }
        return reused, carried
    return None, carried


def build_chunks_for_document(profile: DocumentProfile, lines: Optional[list[Line]] = None) -> list[dict[str, Any]]:
    extracted = classify_lines(lines if lines is not None else extract_lines(profile.pdf_path))
    spans = _table_spans(extracted)
    consumed = {index for start, end in spans for index in range(start, end + 1)}
    span_at = {start: end for start, end in spans}
    chunks: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    pending: list[Line] = []
    carried_unit: Optional[dict[str, Any]] = None
    carried_section = ""
    page_counts: dict[int, int] = {}

    def emit(kind: str, chunk_lines: list[Line], text: str, section: list[dict[str, Any]]) -> None:
        nonlocal carried_unit, carried_section
        if not text.strip():
            return
        page = chunk_lines[0].page
        page_counts[page] = page_counts.get(page, 0) + 1
        cells = [cell for line in chunk_lines for cell in line.cells]
        period = _period_block(text, cells if kind == "table" else [], section, profile, page)
        section_key = section[-1]["text"] if section else ""
        if kind == "table":
            if section_key != carried_section:
                carried_unit = None
            unit, carried_unit = _apply_unit(text, cells, page, carried_unit)
            carried_section = section_key
        else:
            unit, _ = _apply_unit(text, [], page, None)
        if kind == "paragraph" and ("概不負責" in text or "take no responsibility" in text):
            kind = "boilerplate"
        chunk_id = f"{profile.document_id}:p{page:03d}:c{page_counts[page]:03d}"
        chunks.append(
            {
                "chunk_id": chunk_id,
                "chunker": CHUNKER,
                "document_id": profile.document_id,
                "kind": kind,
                "language": profile.language,
                "text": text,
                "column_separator": COLUMN_SEPARATOR if kind == "table" else None,
                "source": {
                    "pdf_path": profile.raw["download"]["path"],
                    "sha256": profile.sha256,
                    "page": page,
                    "bbox": _bbox(chunk_lines),
                    "anchor": f"pdf page {page}, bbox {_bbox(chunk_lines)}",
                },
                "document": {
                    "snapshot_reporting_period": profile.snapshot_reporting_period,
                    "snapshot_reporting_period_note": "Day 22 manifest 对该 PDF 的报告期标注，不是本块正文。",
                    "title_page": profile.title_page,
                    "title_periods": profile.title_periods,
                },
                "issuer": _issuer_block(profile),
                "section_headings": [{key: value for key, value in item.items() if key != "size"} | {"in_text": item["text"] in text} for item in section],
                "period": period,
                "unit": unit,
            }
        )

    index = 0
    while index < len(extracted):
        if index in consumed:
            end = span_at[index]
            table_lines = extracted[index:end + 1]
            for line in table_lines:
                _push_section(stack, line)
            pending = [line for line in pending if line not in table_lines]
            emit("table", table_lines, "\n".join(line.text for line in table_lines), list(stack))
            index = end + 1
            continue
        line = extracted[index]
        if line.kind == "furniture":
            index += 1
            continue
        if line.kind in {"heading", "caption"}:
            _push_section(stack, line)
            pending.append(line)
            index += 1
            continue
        paragraph = [line]
        index += 1
        while index < len(extracted) and index not in consumed and extracted[index].kind == "prose" and _same_paragraph(paragraph[-1], extracted[index]):
            paragraph.append(extracted[index])
            index += 1
        prefix: list[Line] = []
        if pending and pending[-1].page == paragraph[0].page and paragraph[0].y0 - pending[-1].y0 <= 70:
            prefix = pending
            pending = []
        else:
            pending = []
        body = prefix + paragraph
        pieces = _split_long_paragraph(_join_paragraph(body, profile.language), profile.language)
        if len(pieces) == 1:
            emit("paragraph", body, pieces[0], list(stack))
        else:
            for piece in pieces:
                emit("paragraph", body, piece, list(stack))
    for line in pending:
        emit("heading", [line], line.text.strip(), list(stack))
    return chunks


def build_filing_chunks(manifest_path: Path = DEFAULT_MANIFEST, root: Path = ROOT) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for raw in load_manifest_documents(manifest_path):
        profile = build_profile(raw, root)
        chunks.extend(build_chunks_for_document(profile))
    ids = [chunk["chunk_id"] for chunk in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("chunk_id collision")
    return chunks


def write_jsonl(chunks: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(chunk, ensure_ascii=False, separators=(",", ":")) + "\n" for chunk in chunks)
    path.write_text(payload, encoding="utf-8")


def summarize(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    documents: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        bucket = documents.setdefault(
            chunk["document_id"],
            {"chunks": 0, "kinds": {}, "pages": set(), "with_unit": 0, "unit_in_chunk": 0, "period_in_chunk": 0},
        )
        bucket["chunks"] += 1
        bucket["kinds"][chunk["kind"]] = bucket["kinds"].get(chunk["kind"], 0) + 1
        bucket["pages"].add(chunk["source"]["page"])
        if chunk["unit"]:
            bucket["with_unit"] += 1
            if chunk["unit"]["evidence_kind"] == "in_chunk":
                bucket["unit_in_chunk"] += 1
        if chunk["period"]["evidence_kind"] == "in_chunk":
            bucket["period_in_chunk"] += 1
    for bucket in documents.values():
        bucket["page_count"] = len(bucket.pop("pages"))
    return {"chunker": CHUNKER, "chunks": len(chunks), "documents": documents}
