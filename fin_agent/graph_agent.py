"""LangGraph version of the existing read-only tool-calling loop."""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import TypedDict

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from fin_agent.tool_contracts import TOOL_SCHEMAS, execute_read_only_tool
from fin_agent.tool_round import RunResult

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    messages: list
    cutoff: str
    tool_calls: int
    status: str
    answer: str


def run_graph_agent(model, question: str, cutoff: str, max_steps: int = 5,
                    timeout_seconds: float = 30, max_retries: int = 1) -> RunResult:
    """Run the same model.complete interface used by the hand-written loop."""
    if max_steps < 0 or max_retries < 0 or timeout_seconds <= 0:
        raise ValueError("max_steps and max_retries must be nonnegative and timeout_seconds positive")
    deadline = time.monotonic() + timeout_seconds
    executor = ThreadPoolExecutor(max_workers=1)
    latest = {"messages": [{"role": "user", "content": question}], "cutoff": cutoff,
              "tool_calls": 0, "status": "running", "answer": ""}

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

    def model_node(state: AgentState):
        response = call_with_deadline(model.complete, list(state["messages"]), TOOL_SCHEMAS)
        messages = state["messages"] + [response]
        if response.get("tool_calls"):
            return {"messages": messages}
        return {"messages": messages, "status": "completed", "answer": response.get("content") or ""}

    def tool_node(state: AgentState):
        messages = list(state["messages"])
        count = state["tool_calls"]
        for call in messages[-1]["tool_calls"]:
            if count >= max_steps:
                return {"messages": messages, "tool_calls": count, "status": "max_steps",
                        "answer": "已达到工具调用次数上限，任务未完成。"}
            call_id = call["id"]
            name = call["function"]["name"]
            count += 1
            logger.info("tool requested id=%s name=%s", call_id, name)
            try:
                arguments = json.loads(call["function"]["arguments"])
                for attempt in range(max_retries + 1):
                    try:
                        result = call_with_deadline(execute_read_only_tool, name, arguments, state["cutoff"])
                        break
                    except (ConnectionError, OSError) as exc:
                        logger.warning("tool error id=%s type=%s attempt=%d", call_id, type(exc).__name__, attempt + 1)
                        if attempt == max_retries:
                            raise
                content = json.dumps(result, ensure_ascii=False)
                logger.info("tool completed id=%s name=%s attempts=%d", call_id, name, attempt + 1)
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                content = json.dumps({"error": {"type": "invalid_request", "message": str(exc)}}, ensure_ascii=False)
            except (ConnectionError, OSError) as exc:
                content = json.dumps({"error": {"type": "tool_unavailable", "message": str(exc)}}, ensure_ascii=False)
            messages.append({"role": "tool", "tool_call_id": call_id, "content": content})
        return {"messages": messages, "tool_calls": count}

    graph = StateGraph(AgentState)
    graph.add_node("model", model_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("model")
    graph.add_conditional_edges("model", lambda state: END if state["status"] == "completed" else "tools")
    graph.add_conditional_edges("tools", lambda state: END if state["status"] == "max_steps" else "model")
    compiled = graph.compile()
    try:
        for update in compiled.stream(latest, config={"recursion_limit": 2 * max_steps + 3}, stream_mode="values"):
            latest = update
        return RunResult(latest["status"], latest["answer"], latest["messages"], latest["tool_calls"])
    except TimeoutError:
        return RunResult("timeout", "已达到总时间限制，任务未完成。", latest["messages"], latest["tool_calls"])
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
