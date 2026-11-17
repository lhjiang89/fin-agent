import time
from unittest.mock import patch

from fin_agent.graph_agent import run_graph_agent
from fin_agent.tool_round import run_agent


def call(name, identifier):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": identifier, "type": "function",
            "function": {"name": name, "arguments": '{"symbol":"HK.00700"}'}}]}


class FakeModel:
    def __init__(self, responses):
        self.responses = iter(responses)

    def complete(self, messages, tools):
        return next(self.responses)


def test_graph_and_manual_produce_same_transcript():
    responses = [call("get_prices", "a"), call("get_filings", "b"), {"role": "assistant", "content": "完成"}]
    with patch("fin_agent.graph_agent.execute_read_only_tool", return_value=[]):
        graph = run_graph_agent(FakeModel(responses), "研究腾讯", "2026-10-22")
    with patch("fin_agent.tool_round.execute_read_only_tool", return_value=[]):
        manual = run_agent(FakeModel(responses), "研究腾讯", "2026-10-22")
    assert graph == manual


def test_graph_stops_at_limit():
    with patch("fin_agent.graph_agent.execute_read_only_tool", return_value=[]):
        result = run_graph_agent(FakeModel([call("get_prices", "a"), call("get_prices", "b")]),
                                 "研究腾讯", "2026-10-22", max_steps=1)
    assert result.status == "max_steps" and result.tool_calls == 1


def test_graph_timeout():
    class SlowModel:
        def complete(self, messages, tools):
            time.sleep(0.15)
            return {"role": "assistant", "content": "迟到"}

    assert run_graph_agent(SlowModel(), "研究腾讯", "2026-10-22", timeout_seconds=0.02).status == "timeout"


def test_graph_returns_validation_error_to_model():
    bad = call("get_prices", "a")
    bad["tool_calls"][0]["function"]["arguments"] = '{"symbol":"UNKNOWN"}'
    result = run_graph_agent(FakeModel([bad, {"role": "assistant", "content": "参数错误"}]),
                             "研究腾讯", "2026-10-22")
    assert 'invalid_request' in result.messages[2]["content"]
