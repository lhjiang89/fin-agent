"""Run one model-proposed tool call and return its result to the model."""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from pydantic import ValidationError

from fin_agent.tool_contracts import TOOL_SCHEMAS, execute_read_only_tool

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    status: str
    answer: str
    messages: list
    tool_calls: int


def run_agent(model, question: str, cutoff: str, max_steps: int = 5, timeout_seconds: float = 30, max_retries: int = 1) -> RunResult:
    """Run a bounded read-only agent; timed-out in-flight calls may finish in background."""
    if max_steps < 0 or timeout_seconds <= 0 or max_retries < 0:
        raise ValueError("max_steps and max_retries must be nonnegative and timeout_seconds positive")
    messages = [{"role": "user", "content": question}]
    deadline = time.monotonic() + timeout_seconds
    executed = 0
    executor = ThreadPoolExecutor(max_workers=1)

    def call_with_deadline(function, *args):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        future = executor.submit(function, *args)
        try:
            return future.result(timeout=remaining)
        except FutureTimeout as exc:
            future.cancel()
            raise TimeoutError from exc

    try:
        while True:
            assistant = call_with_deadline(model.complete, list(messages), TOOL_SCHEMAS)
            calls = assistant.get("tool_calls") or []
            if not calls:
                messages.append(assistant)
                return RunResult("completed", assistant.get("content") or "", messages, executed)
            messages.append(assistant)
            for call in calls:
                if executed >= max_steps:
                    return RunResult("max_steps", "已达到工具调用次数上限，任务未完成。", messages, executed)
                call_id = call["id"]
                name = call["function"]["name"]
                logger.info("tool requested id=%s name=%s", call_id, name)
                executed += 1
                attempts = 0
                try:
                    arguments = json.loads(call["function"]["arguments"])
                    for attempt in range(max_retries + 1):
                        attempts = attempt + 1
                        try:
                            result = call_with_deadline(execute_read_only_tool, name, arguments, cutoff)
                            break
                        except (ConnectionError, OSError) as exc:
                            logger.warning("tool error id=%s type=%s attempt=%d", call_id, type(exc).__name__, attempts)
                            if attempt == max_retries:
                                raise
                    content = json.dumps(result, ensure_ascii=False)
                    logger.info("tool completed id=%s name=%s attempts=%d rows=%d", call_id, name, attempts, len(result))
                except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                    logger.warning("tool error id=%s type=%s attempt=%d", call_id, type(exc).__name__, attempts)
                    content = json.dumps({"error": {"type": "invalid_request", "message": str(exc)}}, ensure_ascii=False)
                except (ConnectionError, OSError) as exc:
                    content = json.dumps({"error": {"type": "tool_unavailable", "message": str(exc)}}, ensure_ascii=False)
                messages.append({"role": "tool", "tool_call_id": call_id,
                                 "content": content})
    except TimeoutError:
        return RunResult("timeout", "已达到总时间限制，任务未完成。", messages, executed)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def run_tool_round(model, question: str, cutoff: str):
    """Run exactly one tool call; model implements complete(messages, tools)."""
    messages = [{"role": "user", "content": question}]
    assistant = model.complete(messages, TOOL_SCHEMAS)
    calls = assistant.get("tool_calls", [])
    if len(calls) != 1:
        raise ValueError("expected exactly one tool call")
    call = calls[0]
    call_id = call["id"]
    name = call["function"]["name"]
    arguments = json.loads(call["function"]["arguments"])
    logger.info("tool requested id=%s name=%s", call_id, name)
    result = execute_read_only_tool(name, arguments, cutoff)
    logger.info("tool completed id=%s name=%s rows=%d", call_id, name, len(result))
    messages.append(assistant)
    messages.append({
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(result, ensure_ascii=False),
    })
    return model.complete(messages, TOOL_SCHEMAS)
