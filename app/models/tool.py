from pydantic import BaseModel, Field


class ToolSelectionResult(BaseModel):
    selected_tools: list[str] = Field(default_factory=list)
    skipped_tools: list[dict[str, str]] = Field(default_factory=list)
    reason: str = ""
    requires_human_followup: bool = False
