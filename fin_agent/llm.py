"""Small DeepSeek client used for the first structured Agent response."""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError


class StockAnswer(BaseModel):
    conclusion: str
    change_percent: Optional[float] = None
    citations: list[str] = Field(default_factory=list)
    as_of: str
    missing_information: list[str] = Field(
        default_factory=list,
        description="Only facts required to answer but absent from the supplied data. Use [] when the answer is supported.",
    )


class AnswerValidationError(ValueError):
    pass


def validate_answer(answer: StockAnswer, visible_rows: list[dict[str, Any]]) -> StockAnswer:
    allowed_dates = {row["date"] for row in visible_rows}
    if any(citation not in allowed_dates for citation in answer.citations):
        raise AnswerValidationError("answer cites a date that is not visible at the cutoff")
    if answer.change_percent is not None and len(visible_rows) < 2:
        raise AnswerValidationError("answer reports a change without two visible daily bars")
    return answer


def _prompt(question: str, visible_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    payload = json.dumps(visible_rows, ensure_ascii=False, indent=2)
    return [
        {"role": "system", "content": "你是 Fin-Agent 的股票研究助手。只使用用户提供的行情数据。请输出 JSON，字段必须是 conclusion、change_percent、citations、as_of、missing_information。citations 只能填写数据中的 date。missing_information 只填写确实阻碍回答的信息，如果提供的数据足以回答问题，必须输出空数组 []，不要把额外背景或可选分析写进去。数据不足时将 change_percent 设为 null。"},
        {"role": "user", "content": f"问题：{question}\n可见行情：\n{payload}"},
    ]


def answer_with_deepseek(question: str, visible_rows: list[dict[str, Any]], model: str = "deepseek-flash") -> StockAnswer:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not visible in this shell. Export it before using --live.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("The openai package is required. Run: python -m pip install openai") from exc
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    request_payload = {
        "model": model,
        "messages": _prompt(question, visible_rows),
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 500,
        "thinking": {"type": "disabled"},
    }
    print(
        "deepseek_request_payload="
        + json.dumps(request_payload, ensure_ascii=False, indent=2),
        file=sys.stderr,
    )
    response = client.chat.completions.create(
        model=model, messages=request_payload["messages"],
        response_format={"type": "json_object"}, temperature=0, max_tokens=500,
        extra_body={"thinking": {"type": "disabled"}},
    )
    print(
        "deepseek_response=" + response.model_dump_json(indent=2),
        file=sys.stderr,
    )
    content = response.choices[0].message.content or ""
    if not content.strip():
        finish_reason = response.choices[0].finish_reason
        raise AnswerValidationError(f"DeepSeek returned empty JSON content (finish_reason={finish_reason})")
    try:
        payload = json.loads(content)
        if isinstance(payload.get("missing_information"), str):
            payload["missing_information"] = [payload["missing_information"]]
        answer = StockAnswer.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        raise AnswerValidationError(f"DeepSeek returned invalid answer JSON: {content!r}") from exc
    return validate_answer(answer, visible_rows)
