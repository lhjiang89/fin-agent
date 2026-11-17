"""Read-only data functions for the agent's tool-calling exercises."""

from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from fin_agent.market_data import load_json_rows, normalize_daily_rows, visible_at


def get_prices(symbol: str, as_of: str, path: str = "fixtures/tencent_daily.json") -> list:
    """Fetch the 30-day window when cached data does not reach the cutoff date."""
    cutoff = datetime.strptime(as_of, "%Y-%m-%d").date()
    cache = Path(path)
    all_rows = load_json_rows(path) if cache.exists() else []
    rows = visible_at([row for row in all_rows if row["symbol"] == symbol], as_of)
    today = datetime.now(ZoneInfo("Asia/Hong_Kong")).date()
    if cutoff < today and any(row["date"] == cutoff.isoformat() for row in rows):
        return rows

    from futu import AuType, KLType, OpenQuoteContext, RET_OK

    context = OpenQuoteContext(host="127.0.0.1", port=11111)
    try:
        raw = []
        page_key = None
        while True:
            ret, data, page_key = context.request_history_kline(
                symbol, start=(cutoff - timedelta(days=30)).isoformat(),
                end=cutoff.isoformat(), ktype=KLType.K_DAY, autype=AuType.QFQ,
                max_count=1000, page_req_key=page_key,
            )
            if ret != RET_OK:
                raise RuntimeError(f"Futu OpenD request failed: {data}")
            raw.extend(data.to_dict(orient="records"))
            if page_key is None:
                break
    finally:
        context.close()

    fetched = visible_at(normalize_daily_rows(raw), as_of)
    if any(row["symbol"] != symbol for row in fetched):
        raise ValueError("Futu returned a different symbol")
    if fetched:
        merged = {(row["symbol"], row["date"]): row for row in all_rows}
        merged.update({(row["symbol"], row["date"]): row for row in fetched})
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sorted(fetched, key=lambda row: row["date"])


def get_filings(symbol: str, as_of: str, path: str = "fixtures/filings.json") -> list:
    """Search Futu notices when the local cache contains no matching filings.

    Futu search returns a limited keyword-ranked result set, not a complete
    historical archive. Its date-only publication times have day precision.
    """
    cutoff = datetime.strptime(as_of, "%Y-%m-%d").date()
    cache = Path(path)
    rows = load_json_rows(path) if cache.exists() else []
    visible = [
        row for row in rows
        if row["symbol"] == symbol
        and datetime.fromisoformat(row["available_at"]).date() <= cutoff
    ]
    if visible:
        return visible

    from futu import NewsSubType, OpenQuoteContext, RET_OK

    context = OpenQuoteContext(host="127.0.0.1", port=11111)
    try:
        code = symbol.split(".", 1)[-1]
        ret, data = context.get_search_news(code, max_count=100, news_sub_type=NewsSubType.NOTICE)
        if ret != RET_OK:
            raise RuntimeError(f"Futu notice search failed: {data}")
        fetched = []
        for item in data.to_dict(orient="records"):
            if symbol not in item["related_securities"] or not item["url"]:
                continue
            published = datetime.strptime(item["publish_time"], "%Y/%m/%d").date()
            fetched.append({
                "symbol": symbol,
                "source_id": item["url"].split("?", 1)[0],
                "title": item["title"],
                "source": item["source"],
                "url": item["url"],
                "available_at": published.isoformat(),
                "time_precision": "day",
            })
    finally:
        context.close()

    if fetched:
        merged = {(row["symbol"], row["source_id"]): row for row in rows}
        merged.update({(row["symbol"], row["source_id"]): row for row in fetched})
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return [row for row in fetched if datetime.fromisoformat(row["available_at"]).date() <= cutoff]
