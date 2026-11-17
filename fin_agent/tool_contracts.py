"""Model-facing tool schemas and application-controlled execution context."""

from datetime import date
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fin_agent.tools import get_filings, get_prices


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    symbol: Literal["HK.00700"] = Field(description="股票代码；当前仅支持腾讯 HK.00700")


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": ToolArguments.model_json_schema(),
        },
    }
    for name, description in (
        ("get_prices", "查询指定股票的历史日线行情。截止日期由应用控制。"),
        ("get_filings", "搜索指定股票的公告标题、日期和来源链接；搜索结果可能不完整。截止日期由应用控制。"),
    )
]


def execute_read_only_tool(name: str, arguments: dict, cutoff: str) -> list:
    """Validate model arguments and inject the user-selected cutoff."""
    if not isinstance(cutoff, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cutoff):
        raise ValueError("cutoff must be YYYY-MM-DD")
    date.fromisoformat(cutoff)
    tools = {"get_prices": get_prices, "get_filings": get_filings}
    if name not in tools:
        raise ValueError(f"unknown tool: {name}")
    validated = ToolArguments.model_validate(arguments)
    return tools[name](symbol=validated.symbol, as_of=cutoff)
