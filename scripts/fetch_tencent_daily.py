"""Fetch Tencent daily K-lines from a local Futu OpenD instance."""

import argparse
import json
from pathlib import Path

from futu import AuType, KLType, OpenQuoteContext, RET_OK

from fin_agent.market_data import normalize_daily_rows


def fetch(symbol: str, count: int) -> tuple[list[dict], list[dict]]:
    context = OpenQuoteContext(host="127.0.0.1", port=11111)
    try:
        ret, data, _page_key = context.request_history_kline(
            symbol, ktype=KLType.K_DAY, autype=AuType.QFQ, max_count=count
        )
        if ret != RET_OK:
            raise RuntimeError(f"Futu OpenD request failed: {data}")
        raw = data.to_dict(orient="records")
        return raw, normalize_daily_rows(raw)
    finally:
        context.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="HK.00700")
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--output-dir", default="fixtures")
    args = parser.parse_args()
    raw, normalized = fetch(args.symbol, args.count)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "tencent_daily.raw.json").write_text(json.dumps(raw, ensure_ascii=False, default=str, indent=2) + "\n")
    (output_dir / "tencent_daily.json").write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n")
    print(f"saved {len(normalized)} daily bars for {args.symbol}")


if __name__ == "__main__":
    main()
