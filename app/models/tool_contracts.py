from pydantic import BaseModel, Field


class ToolRequest(BaseModel):
    tool_name: str
    intent: str
    entities: dict[str, str | list[str]] = Field(default_factory=dict)
    context: dict[str, str] = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool_name: str
    success: bool
    data: dict[str, str] = Field(default_factory=dict)
    summary: str = ""
    error: str | None = None
