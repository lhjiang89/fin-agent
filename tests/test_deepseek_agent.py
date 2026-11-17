from unittest.mock import patch

from openai.types.chat import ChatCompletion

from fin_agent.deepseek_agent import DeepSeekAgentModel
from fin_agent.tool_contracts import TOOL_SCHEMAS


def test_adapter_preserves_tool_call_and_prints_request_response(monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-for-test")
    response = ChatCompletion.model_validate({"id": "r", "object": "chat.completion", "created": 0,
        "model": "deepseek-flash", "choices": [{"index": 0, "finish_reason": "tool_calls",
        "message": {"role": "assistant", "content": None, "tool_calls": [{"id": "call-a", "type": "function",
        "function": {"name": "get_prices", "arguments": '{"symbol":"HK.00700"}'}}]}}]})
    model = DeepSeekAgentModel("2026-11-13")
    with patch.object(model.client.chat.completions, "create", return_value=response):
        message = model.complete([{"role": "user", "content": "腾讯行情"}], TOOL_SCHEMAS)
    assert message["tool_calls"][0]["id"] == "call-a"
    logged = capsys.readouterr().err
    assert "deepseek_request_payload=" in logged and "deepseek_response=" in logged
    assert "secret-for-test" not in logged
