import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fin_agent.llm import StockAnswer, answer_with_deepseek
from fin_agent.market_data import daily_change_percent, load_json_rows, visible_at


def save_trace(trace, directory=Path("runs")):
    directory.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    trace["run_id"] = run_id
    trace["recorded_at"] = datetime.now(timezone.utc).isoformat()
    path = directory / f"{run_id}.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(trace, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


def main():
    parser = argparse.ArgumentParser(description="Fin-Agent 股票研究命令行工具")
    parser.add_argument("--symbol", default="HK.00700", help="标的代码，例如 HK.00700")
    parser.add_argument("--as-of", help="截止日期，格式 YYYY-MM-DD")
    parser.add_argument("--question", default="最近两个交易日涨跌幅是多少？", help="研究问题")
    parser.add_argument("--data", default="fixtures/tencent_daily.json", help="标准化行情 JSON")
    parser.add_argument("--live", action="store_true", help="调用 DeepSeek 生成结构化回答")
    args = parser.parse_args()
    if not args.live:
        print(args.symbol)
        return
    rows = [row for row in load_json_rows(args.data) if row["symbol"] == args.symbol]
    if not rows:
        raise SystemExit(f"no data found for {args.symbol}")
    cutoff = args.as_of or max(row["date"] for row in rows)
    visible_rows = visible_at(rows, cutoff)
    trace = {"model": "deepseek-flash", "prompt_version": "day5-v1", "symbol": args.symbol,
             "as_of": cutoff, "visible_bars": len(visible_rows)}
    print(f"symbol={args.symbol} as_of={cutoff} visible_bars={len(visible_rows)}")
    latest_data_date = max(row["date"] for row in rows)
    if cutoff > latest_data_date:
        gap = f"请求截止日为 {cutoff}，但本地行情最新日期只有 {latest_data_date}"
        answer = StockAnswer(
            conclusion="无法基于当前行情数据回答该截止日期的问题",
            change_percent=None,
            citations=[],
            as_of=cutoff,
            missing_information=[gap],
        )
        print(answer.model_dump_json(indent=2, ensure_ascii=False))
        trace.update(status="skipped", reason="data_coverage_insufficient", citations=[])
        print(f"trace={save_trace(trace)}")
        print("deepseek_skipped=data_coverage_insufficient")
        return
    started = time.perf_counter()
    try:
        answer = answer_with_deepseek(args.question, visible_rows)
    except Exception as exc:
        trace.update(status="error", error_type=type(exc).__name__, elapsed_ms=round((time.perf_counter() - started) * 1000, 2))
        print(f"trace={save_trace(trace)}")
        raise SystemExit(str(exc)) from exc
    print(answer.model_dump_json(indent=2, ensure_ascii=False))
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    trace.update(status="completed", elapsed_ms=elapsed_ms, citations=answer.citations)
    print(f"trace={save_trace(trace)} elapsed_ms={elapsed_ms}")
    if len(visible_rows) >= 2:
        print(f"verified_change_percent={daily_change_percent(visible_rows)}")


if __name__ == "__main__":
    main()
