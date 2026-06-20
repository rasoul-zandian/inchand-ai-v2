from pydantic import BaseModel

from app.models.tool_contracts import ToolResult


class OrderLookupExecutionResult(BaseModel):
    executed: bool
    tool_result: ToolResult | None = None
