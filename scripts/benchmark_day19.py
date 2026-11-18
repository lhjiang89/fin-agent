"""Compare the Week 2 tool loop with a fixed retrieve-then-answer workflow.

Both methods use DeepSeek Flash, the same frozen price/filing snapshot, and
the Day 16 development questions. Tool execution in the tool-loop arm is
replaced by the exact same offline snapshot adapter to prevent data drift.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fin_agent.deepseek_agent import DeepSeekAgentModel
from fin_agent.tool_round import run_agent
from scripts.score_evals import load_jsonl, score_research


ROOT = Path(__file__).resolve().parents[1]
PRICE_PATH = ROOT / "evals/fixtures/day15_prices.json"
FILING_PATH = ROOT / "fixtures/filings.json"
SYSTEM_PROMPT = (
    "你是 Fin-Agent 的离线评测助手。数据截止日期为 {cutoff}，只能使用用户消息或工具返回的数据。"
    "请仅输出 JSON 对象，字段为 action、as_of、citations、missing_information。"
    "action 必须为 answer、insufficient_data 或 reject_future_data。"
    "有计算变化率时加 change_percent；询问单日或多日具体值时，把日期作为键并给数值。"
    "引用只能写证据中的日期；as_of 必须填 {cutoff}。missing_information 必须是字符串数组，只列缺失字段名称。缺少所需字段时明确填写，"
    "不可编造。若问题询问截至日期之后的数据，action 用 reject_future_data。"
)


def read_snapshot() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prices = json.loads(PRICE_PATH.read_text(encoding="utf-8"))
    filings = json.loads(FILING_PATH.read_text(encoding="utf-8"))
    return prices, filings


def offline_tool(name: str, arguments: dict, cutoff: str, prices, filings):
    symbol = arguments.get("symbol")
    if symbol != "HK.00700":
        raise ValueError("offline snapshot only includes HK.00700")
    if name == "get_prices":
        return [row for row in prices if row["symbol"] == symbol and row["date"] <= cutoff]
    if name == "get_filings":
        return [row for row in filings if row["symbol"] == symbol and row["available_at"][:10] <= cutoff]
    raise ValueError(f"unknown tool: {name}")


def parse_answer(content: str) -> dict[str, Any]:
    try:
        payload = json.loads(content or "")
    except json.JSONDecodeError:
        return {"action": "invalid_output", "raw_answer": content}
    if not isinstance(payload, dict):
        return {"action": "invalid_output", "raw_answer": content}
    return payload


def run_baseline(model, case, prices, filings):
    # Fixed order, fixed tools, no model-controlled routing.
    visible_prices = offline_tool("get_prices", {"symbol": case["symbol"]}, case["as_of"], prices, filings)
    visible_filings = offline_tool("get_filings", {"symbol": case["symbol"]}, case["as_of"], prices, filings)
    numeric_fields = ["change_percent"] if case.get("expected_change_percent") is not None else list(case.get("expected_values", {}))
    user_message = {
        "role": "user",
        "content": (
            f"截止日期：{case['as_of']}\n问题：{case['question']}\n"
            f"数值字段键必须使用：{json.dumps(numeric_fields, ensure_ascii=False)}。\n"
            f"固定顺序取得的行情数据：{json.dumps(visible_prices, ensure_ascii=False)}\n"
            f"固定顺序取得的公告数据：{json.dumps(visible_filings, ensure_ascii=False)}"
        ),
    }
    response = model.complete([user_message], [])
    return parse_answer(response.get("content") or ""), 0, 2


def metric_delta(before, after):
    return {key: after[key] - before[key] for key in before}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--limit", type=int, default=0, help="0 runs every Day 16 dev case")
    args = parser.parse_args()
    cases = [case for case in load_jsonl(ROOT / "evals/research_cases.jsonl") if case["split"] == "dev"]
    if args.limit:
        cases = cases[:args.limit]
    prices, filings = read_snapshot()
    results = {"baseline": [], "tool_loop": []}
    result_by_arm = {"baseline": [], "tool_loop": []}
    for case in cases:
        for arm in ("baseline", "tool_loop"):
            model = DeepSeekAgentModel(case["as_of"], model=args.model, system_prompt=SYSTEM_PROMPT)
            before = dict(model.metrics)
            started = time.perf_counter()
            if arm == "baseline":
                prediction, tool_calls, fixed_tool_calls = run_baseline(model, case, prices, filings)
                status = "completed"
            else:
                import fin_agent.tool_round as tool_round

                original_executor = tool_round.execute_read_only_tool
                tool_round.execute_read_only_tool = lambda name, arguments, cutoff: offline_tool(
                    name, arguments, cutoff, prices, filings
                )
                try:
                    numeric_fields = ["change_percent"] if case.get("expected_change_percent") is not None else list(case.get("expected_values", {}))
                    agent_question = (
                        f"{case['question']}\n请仅输出 JSON；数值字段键必须使用 "
                        f"{json.dumps(numeric_fields, ensure_ascii=False)}。"
                    )
                    output = run_agent(model, agent_question, case["as_of"], timeout_seconds=60)
                finally:
                    tool_round.execute_read_only_tool = original_executor
                status = output.status
                tool_calls = output.tool_calls
                fixed_tool_calls = None
                prediction = parse_answer(output.answer)
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            scored_prediction = {"case_id": case["id"], **prediction}
            result_by_arm[arm].append(scored_prediction)
            results[arm].append({
                "case_id": case["id"], "status": status, "prediction": prediction,
                "tool_calls": tool_calls, "fixed_data_calls": fixed_tool_calls,
                "elapsed_ms": elapsed_ms, "usage": metric_delta(before, model.metrics),
                "unanswerable": prediction.get("action") == "insufficient_data",
            })
            print(f"day19 arm={arm} case={case['id']} status={status} elapsed_ms={elapsed_ms}")

    report = {
        "run_id": uuid.uuid4().hex,
        "created_at": datetime.now().astimezone().isoformat(),
        "model": args.model,
        "snapshot": {"prices": str(PRICE_PATH.relative_to(ROOT)), "filings": str(FILING_PATH.relative_to(ROOT))},
        "case_ids": [case["id"] for case in cases],
        "arms": {},
        "caveats": [
            "该实验使用冻结本地数据，不调用 Futu OpenD。",
            "fixed_data_calls 是固定工作流读取的两个数据源数；tool_calls 是 Agent 实际请求并执行的工具数。",
            "无法回答计数由模型 action=insufficient_data 标记；是否恰当由研究题答案评分一并核对。",
            "模型耗时含网络延迟；单次配对且小样本，不足以作统计显著性结论。",
        ],
    }
    for arm in ("baseline", "tool_loop"):
        predictions = result_by_arm[arm]
        score = score_research(cases, predictions)
        all_usage = [item["usage"] for item in results[arm]]
        report["arms"][arm] = {
            "success_count": score["passed"], "case_count": len(cases),
            "answer_pass_rate": score["answer_pass_rate"],
            "dimension_pass_rates": score["dimension_pass_rates"],
            "unanswerable_count": sum(item["unanswerable"] for item in results[arm]),
            "tool_calls": sum(item["tool_calls"] for item in results[arm]),
            "requests": sum(item["requests"] for item in all_usage),
            "prompt_tokens": sum(item["prompt_tokens"] for item in all_usage),
            "completion_tokens": sum(item["completion_tokens"] for item in all_usage),
            "total_tokens": sum(item["total_tokens"] for item in all_usage),
            "elapsed_ms_total": round(sum(item["elapsed_ms"] for item in results[arm]), 2),
            "per_case": results[arm],
        }
    out_dir = ROOT / "evals/runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"day19_{report['run_id']}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(out_path.relative_to(ROOT)), "arms": report["arms"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
