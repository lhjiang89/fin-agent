"""Generate anonymized insufficiency answers and order-swapped LLM judgments."""

from __future__ import annotations

import copy
import json
import random
import uuid
from datetime import datetime
from pathlib import Path

from fin_agent.deepseek_agent import DeepSeekAgentModel
from fin_agent.tool_contracts import TOOL_SCHEMAS
from fin_agent.tool_round import run_agent
from scripts.benchmark_day19 import ROOT, offline_tool, read_snapshot
from scripts.benchmark_day20 import OLD_PRICE_DESCRIPTION, schemas_with_price_description


CASES = [
    {
        "id": "OI-01", "as_of": "2026-11-13",
        "question": "截至 2026-11-13，腾讯的市盈率是多少？如果现有数据无法回答，请说明缺少什么证据以及怎样补齐。",
    },
    {
        "id": "OI-02", "as_of": "2026-11-13",
        "question": "腾讯在 2026-11-13 发布的公告讲了什么？如果现有数据无法确认，请说明检索边界、缺少的证据和下一步。",
    },
]
ANSWER_SYSTEM = (
    "你是 Fin-Agent 股票研究助手。数据截止日期为 {cutoff}。只使用工具结果，不要猜测。"
    "当证据不足时，直接说明现有数据能证明什么、不能证明什么，指出缺少的具体字段或公告原文，"
    "说明检索/数据覆盖限制，并给出补齐证据的下一步。不能把检索未命中说成事件没有发生。"
    "回答控制在 150 字以内，使用自然语言，不要输出 JSON。"
)
JUDGE_SYSTEM = "你是严谨的股票研究答案评审员。只按用户提供的三级标准评分，不猜作者或系统版本。只输出 JSON。"
RUBRIC_TEXT = (
    "等级 2：明确说明证据不足，指出具体缺失字段/期间/原文，准确说明截止日与数据覆盖，"
    "不把检索未命中说成没有发生，并给出可执行的补证步骤。\n"
    "等级 1：没有编造结论且表达了不确定，但缺失原因、覆盖边界或下一步至少有一项不清楚。\n"
    "等级 0：无证据仍给事实/数字、把不完整搜索空结果断言成没有、引用未来或忽略截止时点。"
)


def generate_answer(case, arm, schemas, prices, filings):
    model = DeepSeekAgentModel(case["as_of"], model="deepseek-flash", system_prompt=ANSWER_SYSTEM)
    import fin_agent.tool_round as tool_round

    original_executor = tool_round.execute_read_only_tool
    tool_round.execute_read_only_tool = lambda name, arguments, cutoff: offline_tool(name, arguments, cutoff, prices, filings)
    try:
        result = run_agent(model, case["question"], case["as_of"], timeout_seconds=60, tool_schemas=schemas)
    finally:
        tool_round.execute_read_only_tool = original_executor
    return {
        "arm": arm, "status": result.status, "answer": result.answer,
        "tool_calls": result.tool_calls, "usage": model.metrics,
    }


def judge_pair(case, left_id, left_answer, right_id, right_answer):
    outputs = []
    judge_usage = []
    orders = [(left_id, left_answer, right_id, right_answer), (right_id, right_answer, left_id, left_answer)]
    normalized = []
    for first_id, first_answer, second_id, second_answer in orders:
        prompt = (
            f"场景：{case['question']}\n评分标准：\n{RUBRIC_TEXT}\n"
            f"答案 A：\n{first_answer}\n\n答案 B：\n{second_answer}\n\n"
            "请给 A、B 分别打 0/1/2 分，返回 {\"score_a\":整数,\"reason_a\":字符串,"
            "\"score_b\":整数,\"reason_b\":字符串,\"preferred\":\"A\"|\"B\"|\"tie\",\"pair_reason\":字符串}。"
        )
        model = DeepSeekAgentModel(case["as_of"], model="deepseek-flash", system_prompt=JUDGE_SYSTEM)
        response = model.complete([{"role": "user", "content": prompt}], [])
        judge_usage.append(model.metrics)
        try:
            payload = json.loads(response.get("content") or "")
            outputs.append(payload)
            normalized.append({
                first_id: {"score": payload.get("score_a"), "reason": payload.get("reason_a")},
                second_id: {"score": payload.get("score_b"), "reason": payload.get("reason_b")},
                "preferred_id": first_id if payload.get("preferred") == "A" else second_id if payload.get("preferred") == "B" else "tie",
            })
        except (json.JSONDecodeError, TypeError):
            outputs.append({"invalid_output": response.get("content")})
            normalized.append({"invalid_output": True})
    stability = {}
    for answer_id in (left_id, right_id):
        scores = [item.get(answer_id, {}).get("score") for item in normalized]
        stability[answer_id] = {"scores_by_order": scores, "order_sensitive": scores[0] != scores[1]}
    preference_flip = normalized[0].get("preferred_id") != normalized[1].get("preferred_id")
    return {"raw_outputs": outputs, "normalized_by_answer": normalized, "score_order_sensitivity": stability,
            "preference_flipped_when_swapped": preference_flip, "usage": judge_usage}


def main():
    prices, filings = read_snapshot()
    schema_arms = {
        "original": schemas_with_price_description(OLD_PRICE_DESCRIPTION),
        "revised": copy.deepcopy(TOOL_SCHEMAS),
    }
    mapping = {}
    blind_cases = []
    results = []
    judge_calls = 0
    for case_index, case in enumerate(CASES):
        arms = ("original", "revised") if case_index % 2 == 0 else ("revised", "original")
        arm_results = {arm: generate_answer(case, arm, schema_arms[arm], prices, filings) for arm in arms}
        anon_ids = [f"A{case_index * 2 + 1}", f"A{case_index * 2 + 2}"]
        rng = random.Random(2121 + case_index)
        shuffled = list(zip(arms, anon_ids))
        rng.shuffle(shuffled)
        blind_mapping = {anon_id: arm_results[arm] for arm, anon_id in shuffled}
        mapping[case["id"]] = {anon_id: value["arm"] for anon_id, value in blind_mapping.items()}
        left_id, right_id = anon_ids
        judge = judge_pair(case, left_id, blind_mapping[left_id]["answer"],
                           right_id, blind_mapping[right_id]["answer"])
        judge_calls += 2
        blind_cases.append({
            "case_id": case["id"], "question": case["question"],
            "answers": [{"answer_id": answer_id, "text": blind_mapping[answer_id]["answer"],
                         "human_score": None, "human_rationale": ""} for answer_id in anon_ids],
        })
        results.append({
            "case_id": case["id"], "mapping": mapping[case["id"]],
            "generations": {anon_id: {key: value for key, value in blind_mapping[anon_id].items() if key != "arm"}
                            for anon_id in anon_ids},
            "judge": judge,
        })
        print(f"day21 case={case['id']} tool_calls={sum(value['tool_calls'] for value in arm_results.values())} judge_swapped=yes")

    run_id = uuid.uuid4().hex
    out_dir = ROOT / "evals/runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    blind_path = ROOT / "evals/DAY21_BLIND_REVIEW.md"
    lines = [
        "# Day 21：匿名人工盲评表", "",
        "请先独立阅读 [三级评分规则](DAY21_OPEN_ANSWER_RUBRIC.md)，不要查阅本实验 JSON 中的匿名 ID 映射。",
        "每个答案分别填写 0/1/2 分，并指出支持判断的具体句子。完成后再与模型裁判分数比较。", "",
    ]
    for case in blind_cases:
        lines.extend([f"## {case['case_id']}", "", f"**问题：** {case['question']}", ""])
        for answer in case["answers"]:
            lines.extend([f"### 答案 {answer['answer_id']}", "", answer["text"] or "_（模型未返回文本）_", "",
                          "人工评分（0/1/2）：____    理由与证据：________________________________", ""])
    lines.extend([
        "## 盲评状态", "", "当前分数栏留空，表示真人评审尚未完成；模型裁判结果不能替代人工盲评。完成后可把评分填入此表，"
        "并与 `evals/runs/day21_" + run_id + ".json` 中的模型裁判结果对照。", "",
    ])
    blind_path.write_text("\n".join(lines), encoding="utf-8")
    report = {
        "run_id": run_id, "created_at": datetime.now().astimezone().isoformat(),
        "model": "deepseek-flash",
        "cases": [{key: value for key, value in result.items() if key != "mapping"} for result in results],
        "judge_call_count": judge_calls,
        "judge_summary": {
            "answer_score_order_sensitivity_count": sum(
                result["judge"]["score_order_sensitivity"][answer_id]["order_sensitive"]
                for result in results for answer_id in result["mapping"]
            ),
            "pair_preference_flip_count": sum(result["judge"]["preference_flipped_when_swapped"] for result in results),
        },
        "limitation": "匿名输出由同一模型在两套工具描述下生成；裁判由同一模型运行，且答案具有高度相关性。人工盲评尚待填写。",
    }
    report_path = out_dir / f"day21_{run_id}.json"
    answer_key_path = out_dir / f"day21_answer_key_{run_id}.json"
    answer_key_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path.relative_to(ROOT)), "blind_packet": str(blind_path.relative_to(ROOT)),
                      "judge_summary": report["judge_summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
