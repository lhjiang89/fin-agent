import json
from unittest.mock import patch

import pandas as pd

from fin_agent.tools import get_filings, get_prices


def test_tools_filter_symbol_and_cutoff(tmp_path):
    prices = tmp_path / "prices.json"
    prices.write_text(json.dumps([
        {"symbol": "HK.00700", "date": "2025-11-19"},
        {"symbol": "HK.00700", "date": "2025-11-20"},
        {"symbol": "HK.00005", "date": "2025-11-19"},
    ]))
    filings = tmp_path / "filings.json"
    filings.write_text(json.dumps([
        {"symbol": "HK.00700", "source_id": "E1", "available_at": "2025-11-19T18:00:00+08:00"},
        {"symbol": "HK.00700", "source_id": "E2", "available_at": "2025-11-20T09:00:00+08:00"},
    ]))
    assert [row["date"] for row in get_prices("HK.00700", "2025-11-19", str(prices))] == ["2025-11-19"]
    assert [row["source_id"] for row in get_filings("HK.00700", "2025-11-19", str(filings))] == ["E1"]


def test_missing_cache_fetches_and_persists(tmp_path):
    cache = tmp_path / "prices.json"
    bar = {"code": "HK.00700", "time_key": "2025-11-19 00:00:00", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 100}
    with patch("futu.OpenQuoteContext") as context_class:
        context = context_class.return_value
        context.request_history_kline.return_value = (0, pd.DataFrame([bar]), None)
        assert get_prices("HK.00700", "2025-11-19", str(cache))[0]["date"] == "2025-11-19"
        assert get_prices("HK.00700", "2025-11-19", str(cache))[0]["symbol"] == "HK.00700"
        assert context.request_history_kline.call_count == 1
        context.close.assert_called_once()


def test_stale_cache_fetches_requested_period(tmp_path):
    cache = tmp_path / "prices.json"
    cache.write_text(json.dumps([{"symbol": "HK.00700", "date": "2025-12-29", "close": 591.2}]))
    bar = {"code": "HK.00700", "time_key": "2026-11-13 00:00:00", "open": 600, "high": 610, "low": 590, "close": 605, "volume": 100}
    with patch("futu.OpenQuoteContext") as context_class:
        context = context_class.return_value
        context.request_history_kline.return_value = (0, pd.DataFrame([bar]), None)
        result = get_prices("HK.00700", "2026-11-16", str(cache))
    assert [row["date"] for row in result] == ["2026-11-13"]
    assert context.request_history_kline.call_args.kwargs["end"] == "2026-11-16"
    assert len(json.loads(cache.read_text())) == 2


def test_filing_search_filters_symbol_and_future_dates(tmp_path):
    cache = tmp_path / "filings.json"
    records = [
        {"title": "notice", "source": "HKEX", "url": "https://example.org/1", "publish_time": "2026/10/22", "related_securities": ["HK.00700"]},
        {"title": "other", "source": "HKEX", "url": "https://example.org/2", "publish_time": "2026/10/20", "related_securities": ["HK.00005"]},
        {"title": "future", "source": "HKEX", "url": "https://example.org/3", "publish_time": "2026/10/23", "related_securities": ["HK.00700"]},
    ]
    with patch("futu.OpenQuoteContext") as context_class:
        context = context_class.return_value
        context.get_search_news.return_value = (0, pd.DataFrame(records))
        result = get_filings("HK.00700", "2026-10-22", str(cache))
        assert [row["title"] for row in result] == ["notice"]
        assert result[0]["time_precision"] == "day"
        assert len(json.loads(cache.read_text())) == 2
        context.close.assert_called_once()
