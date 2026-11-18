"""DeepSeek Chat Completions adapter for the read-only agent loop."""

import json
import os
import sys

from openai import OpenAI


class DeepSeekAgentModel:
    def __init__(self, cutoff, model="deepseek-flash", system_prompt=None):
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise RuntimeError("请设置 DEEPSEEK_API_KEY")
        self.client = OpenAI(api_key=key, base_url="https://api.deepseek.com", timeout=20, max_retries=0)
        self.model = model
        self.cutoff = cutoff
        self.system_prompt = system_prompt
        self.metrics = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def complete(self, messages, tools):
        system_content = self.system_prompt.replace("{cutoff}", self.cutoff) if self.system_prompt else (
            f"你是股票研究助手。数据截止日期为 {self.cutoff}，由程序控制。"
            "用户未指定股票时请先询问，不要猜测。仅使用工具返回的证据，"
            "说明引用日期、来源和数据局限，缺少数据时如实说明。当天日线可能尚未收盘，不能称为最终收盘价。回答控制在200字以内，不要列出完整表格。"
        )
        system = {"role": "system", "content": system_content}
        payload = {"model": self.model, "messages": [system] + messages, "tools": tools,
                   "temperature": 0, "max_tokens": 600, "thinking": {"type": "disabled"}}
        print("deepseek_request_payload=" + json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        response = self.client.chat.completions.create(
            model=self.model, messages=payload["messages"], tools=tools, temperature=0,
            max_tokens=600, extra_body={"thinking": {"type": "disabled"}},
        )
        print("deepseek_response=" + response.model_dump_json(indent=2), file=sys.stderr)
        self.metrics["requests"] += 1
        if response.usage is not None:
            self.metrics["prompt_tokens"] += response.usage.prompt_tokens or 0
            self.metrics["completion_tokens"] += response.usage.completion_tokens or 0
            self.metrics["total_tokens"] += response.usage.total_tokens or 0
        choice = response.choices[0]
        if choice.finish_reason not in ("stop", "tool_calls"):
            raise RuntimeError(f"模型未正常完成: {choice.finish_reason}")
        return choice.message.model_dump(exclude_none=True, include={"role", "content", "tool_calls"})
