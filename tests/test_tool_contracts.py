from unittest.mock import patch

import pytest
from pydantic import ValidationError

from fin_agent.tool_contracts import TOOL_SCHEMAS, execute_read_only_tool


def test_tool_arguments_cannot_override_cutoff():
    with patch("fin_agent.tool_contracts.get_prices", return_value=[]) as prices:
        execute_read_only_tool("get_prices", {"symbol": "HK.00700"}, "2026-10-22")
        prices.assert_called_once_with(symbol="HK.00700", as_of="2026-10-22")
        with pytest.raises(ValidationError):
            execute_read_only_tool("get_prices", {"symbol": "HK.00700", "as_of": "2027-01-01"}, "2026-10-22")
        prices.assert_called_once()


@pytest.mark.parametrize("name,arguments,cutoff", [
    ("get_prices", {"symbol": "HK.99999"}, "2026-10-22"),
    ("get_prices", {"symbol": "HK.00700"}, "2026-02-30"),
    ("unknown", {"symbol": "HK.00700"}, "2026-10-22"),
])
def test_invalid_calls_are_rejected(name, arguments, cutoff):
    with pytest.raises(ValueError):
        execute_read_only_tool(name, arguments, cutoff)


def test_schemas_are_model_facing_and_forbid_extra_fields():
    assert {item["function"]["name"] for item in TOOL_SCHEMAS} == {"get_prices", "get_filings"}
    assert all(item["function"]["parameters"]["additionalProperties"] is False for item in TOOL_SCHEMAS)
