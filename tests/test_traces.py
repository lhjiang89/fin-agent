import json

from fin_agent.__main__ import save_trace


def test_consecutive_traces_are_preserved(tmp_path):
    first = save_trace({"status": "completed", "symbol": "HK.00700"}, tmp_path)
    second = save_trace({"status": "error", "symbol": "HK.00700"}, tmp_path)
    assert first != second
    assert json.loads(first.read_text())["status"] == "completed"
    assert json.loads(second.read_text())["status"] == "error"
    assert len(list(tmp_path.glob("*.json"))) == 2
