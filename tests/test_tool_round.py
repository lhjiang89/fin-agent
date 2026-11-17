import json
import logging
from unittest.mock import patch

from fin_agent.tool_round import run_agent, run_tool_round


class FakeModel:
    def __init__(self):
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append(list(messages))
        if len(self.requests) == 1:
            return {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "call-123", "type": "function", "function": {
                    "name": "get_prices", "arguments": '{"symbol":"HK.00700"}',
                }}],
            }
        result = json.loads(messages[-1]["content"])
        return {"role": "assistant", "content": f"收盘价 {result[0]['close']}"}


def test_one_tool_round_preserves_call_id_and_result(caplog):
    model = FakeModel()
    with patch("fin_agent.tool_contracts.get_prices", return_value=[{"close": 618.2}]) as prices:
        with caplog.at_level(logging.INFO):
            answer = run_tool_round(model, "查询腾讯收盘价", "2025-11-19")
    prices.assert_called_once_with(symbol="HK.00700", as_of="2025-11-19")
    assert model.requests[1][-1]["tool_call_id"] == "call-123"
    assert answer["content"] == "收盘价 618.2"
    assert sum("call-123" in record.message for record in caplog.records) == 2


class SequenceModel:
    def __init__(self, responses):
        self.responses = iter(responses)

    def complete(self, messages, tools):
        return next(self.responses)


def tool_call(name, call_id):
    return {"role": "assistant", "content": None, "tool_calls": [{
        "id": call_id, "type": "function", "function": {
            "name": name, "arguments": '{"symbol":"HK.00700"}',
        },
    }]}


def test_agent_completes_after_two_tools():
    model = SequenceModel([tool_call("get_prices", "a"), tool_call("get_filings", "b"),
                           {"role": "assistant", "content": "研究完成"}])
    with patch("fin_agent.tool_round.execute_read_only_tool", return_value=[]) as execute:
        result = run_agent(model, "研究腾讯", "2026-10-22")
    assert result.status == "completed"
    assert result.answer == "研究完成"
    assert result.tool_calls == 2
    assert [message["tool_call_id"] for message in result.messages if message["role"] == "tool"] == ["a", "b"]
    assert execute.call_count == 2


def test_agent_stops_repeated_calls_at_limit():
    model = SequenceModel([tool_call("get_prices", str(i)) for i in range(3)])
    with patch("fin_agent.tool_round.execute_read_only_tool", return_value=[]) as execute:
        result = run_agent(model, "研究腾讯", "2026-10-22", max_steps=2)
    assert result.status == "max_steps"
    assert result.tool_calls == execute.call_count == 2


def test_agent_returns_on_total_timeout():
    import time

    class SlowModel:
        def complete(self, messages, tools):
            time.sleep(0.15)
            return {"role": "assistant", "content": "迟到的回答"}

    started = time.monotonic()
    result = run_agent(SlowModel(), "研究腾讯", "2026-10-22", timeout_seconds=0.02)
    assert result.status == "timeout"
    assert time.monotonic() - started < 0.12


def test_invalid_arguments_return_error_without_retry():
    bad = tool_call("get_prices", "bad")
    bad["tool_calls"][0]["function"]["arguments"] = '{"symbol":"UNKNOWN"}'
    model = SequenceModel([bad, {"role": "assistant", "content": "参数错误"}])
    with patch("fin_agent.tool_contracts.get_prices") as prices:
        result = run_agent(model, "查询", "2026-10-22")
    prices.assert_not_called()
    assert json.loads(result.messages[2]["content"])["error"]["type"] == "invalid_request"
    assert result.tool_calls == 1


def test_transient_failure_retries_within_budget():
    model = SequenceModel([tool_call("get_prices", "retry"), {"role": "assistant", "content": "完成"}])
    with patch("fin_agent.tool_round.execute_read_only_tool", side_effect=[ConnectionError("temporary"), []]) as execute:
        result = run_agent(model, "查询", "2026-10-22", max_retries=1)
    assert result.status == "completed"
    assert execute.call_count == 2


def test_unknown_tool_returns_error():
    model = SequenceModel([tool_call("unknown", "bad"), {"role": "assistant", "content": "工具不存在"}])
    result = run_agent(model, "查询", "2026-10-22")
    assert json.loads(result.messages[2]["content"])["error"]["type"] == "invalid_request"
