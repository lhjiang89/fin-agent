"""Run both implementations against the same deterministic tool call."""

from unittest.mock import patch

from fin_agent.graph_agent import run_graph_agent
from fin_agent.tool_round import run_agent


class DemoModel:
    def complete(self, messages, tools):
        if messages[-1]["role"] == "tool":
            return {"role": "assistant", "content": "已读取腾讯行情。"}
        return {"role": "assistant", "content": None, "tool_calls": [{
            "id": "demo-1", "type": "function",
            "function": {"name": "get_prices", "arguments": '{"symbol":"HK.00700"}'},
        }]}


def main():
    sample = [{"symbol": "HK.00700", "date": "2025-11-19", "close": 617.2}]
    for label, runner, target in (
        ("manual", run_agent, "fin_agent.tool_round.execute_read_only_tool"),
        ("langgraph", run_graph_agent, "fin_agent.graph_agent.execute_read_only_tool"),
    ):
        with patch(target, return_value=sample):
            result = runner(DemoModel(), "查询腾讯行情", "2025-11-19")
        print(f"{label}: status={result.status}, tool_calls={result.tool_calls}, answer={result.answer}")


if __name__ == "__main__":
    main()
