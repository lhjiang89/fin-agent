import pytest

from fin_agent.llm import AnswerValidationError, StockAnswer, validate_answer


def visible_rows():
    return [{"date": "2026-11-12", "close": 600}, {"date": "2026-11-13", "close": 618}]


def test_answer_citations_must_be_visible():
    answer = StockAnswer(conclusion="上涨", change_percent=3, citations=["2026-11-14"], as_of="2026-11-13")
    with pytest.raises(AnswerValidationError):
        validate_answer(answer, visible_rows())


def test_valid_answer_passes():
    answer = StockAnswer(conclusion="上涨", change_percent=3, citations=["2026-11-12", "2026-11-13"], as_of="2026-11-13")
    assert validate_answer(answer, visible_rows()).change_percent == 3


def test_complete_answer_can_have_empty_missing_information():
    answer = StockAnswer(conclusion="上涨", change_percent=3, citations=["2026-11-12", "2026-11-13"], as_of="2026-11-13", missing_information=[])
    assert validate_answer(answer, visible_rows()).missing_information == []


def test_deepseek_logs_request_and_raw_response(monkeypatch, capsys):
    import json
    from types import SimpleNamespace
    import openai
    from fin_agent.llm import answer_with_deepseek

    payload = {"conclusion": "上涨", "change_percent": 3, "citations": ["2026-11-13"],
               "as_of": "2026-11-13", "missing_information": []}
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)), finish_reason="stop")],
        model_dump_json=lambda indent: json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {"total_tokens": 10}}),
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: client)
    answer_with_deepseek("涨跌幅", visible_rows())
    output = capsys.readouterr().err
    assert "deepseek_request_payload=" in output
    assert "deepseek_response=" in output
    assert "total_tokens" in output
    assert "test-secret" not in output
