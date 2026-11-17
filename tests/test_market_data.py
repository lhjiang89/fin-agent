import pytest

from fin_agent.market_data import daily_change_percent, normalize_daily_rows, visible_at


def rows():
    return [
        {"code": "HK.00700", "time_key": "2026-11-12 00:00:00", "open": 600, "high": 610, "low": 590, "close": 600, "volume": 100},
        {"code": "HK.00700", "time_key": "2026-11-13 00:00:00", "open": 600, "high": 630, "low": 595, "close": 618, "volume": 200},
    ]


def test_normalize_filter_and_change():
    normalized = normalize_daily_rows(rows())
    assert normalized[0]["symbol"] == "HK.00700"
    assert [row["date"] for row in visible_at(normalized, "2026-11-12")] == ["2026-11-12"]
    assert daily_change_percent(normalized) == 3.0


def test_missing_field_is_rejected():
    broken = rows()[0].copy()
    del broken["close"]
    with pytest.raises(ValueError, match="close"):
        normalize_daily_rows([broken])


def test_other_symbol_is_preserved_for_later_filtering():
    normalized = normalize_daily_rows(rows() + [{**rows()[0], "code": "HK.00005"}])
    assert {row["symbol"] for row in normalized} == {"HK.00700", "HK.00005"}
