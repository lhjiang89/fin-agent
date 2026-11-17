"""Futu OpenD market-data adapter used by the first Agent milestone."""

from datetime import datetime
from typing import Any, Iterable


def normalize_daily_rows(rows: Iterable[dict[str, Any]], source: str = "futu-opend") -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        required = {"code", "time_key", "open", "high", "low", "close", "volume"}
        missing = required.difference(row)
        if missing:
            raise ValueError(f"missing market-data fields: {sorted(missing)}")
        normalized.append({
            "symbol": row["code"], "market": row["code"].split(".", 1)[0], "period": "1d",
            "date": str(row["time_key"])[:10], "open": float(row["open"]), "high": float(row["high"]),
            "low": float(row["low"]), "close": float(row["close"]), "volume": int(row["volume"]), "source": source,
        })
    return normalized


def visible_at(rows: Iterable[dict[str, Any]], cutoff_date: str) -> list[dict[str, Any]]:
    cutoff = datetime.strptime(cutoff_date, "%Y-%m-%d").date()
    return [row for row in rows if datetime.strptime(row["date"], "%Y-%m-%d").date() <= cutoff]


def load_json_rows(path: str) -> list[dict[str, Any]]:
    import json
    with open(path, encoding="utf-8") as handle:
        rows = json.load(handle)
    if not isinstance(rows, list):
        raise ValueError("market-data file must contain a JSON list")
    return rows


def daily_change_percent(rows: list[dict[str, Any]]) -> float:
    if len(rows) < 2:
        raise ValueError("at least two daily bars are required")
    ordered = sorted(rows, key=lambda row: row["date"])
    previous, latest = ordered[-2], ordered[-1]
    if previous["close"] == 0:
        raise ValueError("previous close cannot be zero")
    return round((latest["close"] - previous["close"]) / previous["close"] * 100, 6)
