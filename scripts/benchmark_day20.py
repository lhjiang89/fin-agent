"""Paired experiment for one tool-description revision and one holdout pass."""

from __future__ import annotations

import argparse
import copy
import json
import time
import uuid
from datetime import datetime
from pathlib import Path

from fin_agent.deepseek_agent import DeepSeekAgentModel
from fin_agent.tool_contracts import TOOL_SCHEMAS
from fin_agent.tool_round import run_agent
from scripts.benchmark_day19 import ROOT, SYSTEM_PROMPT, offline_tool, read_snapshot
from scripts.score_evals import load_jsonl, score_research


OLD_PRICE_DESCRIPTION = "查询指定股票的历史日线行情。截止日期由应用控制。"


def schemas_with_price_description(description):
    schemas = copy.deepcopy(TOOL_SCHEMAS)
    for schema in schemas:
        if schema["function"]["name"] == "get_prices":
            schema["function"]["description"] = description
    return schemas


def run_one(case, schemas, prices, filings, model_name):
    model = DeepSeekAgentModel(case["as_of"], model=model_name, system_prompt=SYSTEM_PROMPT)
    numeric_fields = ["change_percent"] if case.get("expected_change_percent") is not None else list(case.get("expected_values", {}))
    question = (
        f"{case['question']}\n请仅输出 JSON；数值字段键必须使用 "
        f"{json.dumps(numeric_fields, ensure_ascii=False)}。"
    )
    import fin_agent.tool_round as tool_round

    original_executor = tool_round.execute_read_only_tool
    tool_round.execute_read_only_tool = lambda name, arguments, cutoff: offline_tool(
        name, arguments, cutoff, prices, filings
    )
    started = time.perf_counter()
    try:
        result = run_agent(model, question, case["as_of"], timeout_seconds=60, tool_schemas=schemas)
    finally:
        tool_round.execute_read_only_tool = original_executor
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    try:
        prediction = json.loads(result.answer or "")
        if not isinstance(prediction, dict):
            raise ValueError("answer must be a JSON object")
    except (json.JSONDecodeError, ValueError):
        prediction = {"action": "invalid_output", "raw_answer": result.answer}
    return {
        "case_id": case["id"], "status": result.status, "prediction": prediction,
        "tool_calls": result.tool_calls, "elapsed_ms": elapsed_ms,
        "usage": dict(model.metrics), "unanswerable": prediction.get("action") == "insufficient_data",
    }


def summarize(cases, rows):
    expanded_cases = []
    predictions = []
    for index, row in enumerate(rows):
        source_case = next(case for case in cases if case["id"] == row["case_id"])
        unique_id = f"{row['case_id']}__run{index + 1}"
        expanded_cases.append({**source_case, "id": unique_id})
        predictions.append({"case_id": unique_id, **row["prediction"]})
    score = score_research(expanded_cases, predictions)
    requests = sum(row["usage"]["requests"] for row in rows)
    prompt_tokens = sum(row["usage"]["prompt_tokens"] for row in rows)
    completion_tokens = sum(row["usage"]["completion_tokens"] for row in rows)
    total_tokens = sum(row["usage"]["total_tokens"] for row in rows)
    successful = score["passed"]
    return {
        "success_count": successful, "case_count": len(cases), "answer_pass_rate": score["answer_pass_rate"],
        "dimension_pass_rates": score["dimension_pass_rates"], "unanswerable_count": sum(row["unanswerable"] for row in rows),
        "requests": requests, "tool_calls": sum(row["tool_calls"] for row in rows),
        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": total_tokens,
        "elapsed_ms_total": round(sum(row["elapsed_ms"] for row in rows), 2),
        "tokens_per_success": total_tokens / successful if successful else None,
        "errors": score["errors"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0, help="Development-only smoke run; holdout is skipped")
    parser.add_argument("--skip-holdout", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    all_cases = load_jsonl(ROOT / "evals/research_cases.jsonl")
    dev_cases = [case for case in all_cases if case["split"] == "dev"]
    holdout_cases = [case for case in all_cases if case["split"] == "holdout"]
    if args.limit:
        dev_cases = dev_cases[:args.limit]
        args.skip_holdout = True
    prices, filings = read_snapshot()
    run_id = uuid.uuid4().hex
    out_dir = ROOT / "evals/runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    partial_path = out_dir / f"day20_{run_id}.partial.json"
    schemas = {
        "original": schemas_with_price_description(OLD_PRICE_DESCRIPTION),
        "revised": copy.deepcopy(TOOL_SCHEMAS),
    }
    dev_rows = {"original": [], "revised": []}
    pair_results = []
    holdout_rows = {"original": [], "revised": []}
    for repeat in range(1, args.repeats + 1):
        for case_index, case in enumerate(dev_cases):
            order = ("original", "revised") if (repeat + case_index) % 2 else ("revised", "original")
            pair = {"repeat": repeat, "case_id": case["id"], "order": list(order), "arms": {}}
            for arm in order:
                row = run_one(case, schemas[arm], prices, filings, args.model)
                dev_rows[arm].append(row)
                pair["arms"][arm] = row
                print(f"day20 split=dev repeat={repeat} arm={arm} case={case['id']} status={row['status']} elapsed_ms={row['elapsed_ms']}")
            pair_results.append(pair)
            partial_path.write_text(json.dumps({"run_id": run_id, "dev_rows": dev_rows,
                                                "pairs": pair_results, "holdout_rows": holdout_rows},
                                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not args.skip_holdout:
        # One final paired pass on the frozen holdout, after the prompt change is fixed.
        for case_index, case in enumerate(holdout_cases):
            order = ("original", "revised") if case_index % 2 else ("revised", "original")
            for arm in order:
                row = run_one(case, schemas[arm], prices, filings, args.model)
                holdout_rows[arm].append(row)
                print(f"day20 split=holdout repeat=1 arm={arm} case={case['id']} status={row['status']} elapsed_ms={row['elapsed_ms']}")
                partial_path.write_text(json.dumps({"run_id": run_id, "dev_rows": dev_rows,
                                                    "pairs": pair_results, "holdout_rows": holdout_rows},
                                                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dev_summary = {arm: summarize(dev_cases * args.repeats, rows) for arm, rows in dev_rows.items()}
    paired_deltas = []
    for pair in pair_results:
        base = pair["arms"]["original"]
        revised = pair["arms"]["revised"]
        pair["success_delta_revised_minus_original"] = int(
            all(score_research([next(c for c in dev_cases if c["id"] == pair["case_id"])], [
                {"case_id": pair["case_id"], **row["prediction"]}
            ])["passed"] == 1 for row in [revised])
        ) - int(
            all(score_research([next(c for c in dev_cases if c["id"] == pair["case_id"])], [
                {"case_id": pair["case_id"], **row["prediction"]}
            ])["passed"] == 1 for row in [base])
        )
        paired_deltas.append(pair["success_delta_revised_minus_original"])
    report = {
        "run_id": run_id, "created_at": datetime.now().astimezone().isoformat(), "model": args.model,
        "change": {
            "only_change": "get_prices tool description",
            "original": OLD_PRICE_DESCRIPTION,
            "revised": next(s["function"]["description"] for s in TOOL_SCHEMAS if s["function"]["name"] == "get_prices"),
        },
        "snapshot": {"prices": "evals/fixtures/day15_prices.json", "filings": "fixtures/filings.json"},
        "development": {"questions": len(dev_cases), "repeats": args.repeats, "run_count_per_arm": len(dev_rows["original"]),
                        "arms": dev_summary, "paired_success_delta_mean": sum(paired_deltas) / len(paired_deltas) if paired_deltas else None,
                        "pairs": pair_results},
        "holdout": None if args.skip_holdout else {
            "questions": len(holdout_cases), "repeats": 1,
            "arms": {arm: {**summarize(holdout_cases, rows), "per_case": rows} for arm, rows in holdout_rows.items()},
        },
        "development_per_case": dev_rows,
        "caveats": [
            "冻结快照离线回放，不连接 Futu OpenD。",
            "开发集同题配对交替运行，记录重复结果；留出集只在实验末尾运行一次，结果未用于调参。",
            "tokens_per_success 是模型 token 成本代理；未换算货币价格。",
            "小样本及三轮重复仍不足以推断生产流量表现。",
        ],
    }
    output = out_dir / f"day20_{report['run_id']}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    partial_path.unlink(missing_ok=True)
    print(json.dumps({"report": str(output.relative_to(ROOT)), "development": dev_summary,
                      "holdout": report["holdout"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
