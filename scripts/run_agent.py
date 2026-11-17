"""Run the real DeepSeek tool-calling agent with either orchestrator."""

import argparse
import logging
import re
import time

from fin_agent.__main__ import save_trace
from fin_agent.deepseek_agent import DeepSeekAgentModel
from fin_agent.tool_round import run_agent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--engine", choices=("manual", "graph"), default="manual")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if not re.search(r"腾讯|HK\.00700|(?<!\d)00700(?!\d)", args.question, re.IGNORECASE):
        print("请明确指定股票标的；当前工具支持腾讯 HK.00700。")
        path = save_trace({"engine": args.engine, "as_of": args.as_of, "status": "clarification_required",
                           "question": args.question, "tool_calls": 0})
        print(f"status=clarification_required tool_calls=0 trace={path}")
        return
    runner = run_agent
    if args.engine == "graph":
        from fin_agent.graph_agent import run_graph_agent
        runner = run_graph_agent
    started = time.perf_counter()
    model = DeepSeekAgentModel(args.as_of)
    try:
        result = runner(model, args.question, args.as_of, timeout_seconds=60)
    except Exception as exc:
        path = save_trace({"engine": args.engine, "as_of": args.as_of, "status": "error",
                           "error_type": type(exc).__name__, "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)})
        print(f"trace={path}")
        raise
    path = save_trace({"engine": args.engine, "model": model.model, "as_of": args.as_of,
                       "status": result.status, "tool_calls": result.tool_calls,
                       "messages": result.messages, "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)})
    print(result.answer)
    print(f"status={result.status} tool_calls={result.tool_calls} trace={path}")


if __name__ == "__main__":
    main()
