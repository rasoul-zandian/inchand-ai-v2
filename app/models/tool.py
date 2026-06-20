from pydantic import BaseModel, Field

from app.models.tool_contracts import ToolRequest


class ToolSelectionResult(BaseModel):
    selected_tools: list[str] = Field(default_factory=list)
    skipped_tools: list[dict[str, str]] = Field(default_factory=list)
    reason: str = ""
    requires_human_followup: bool = False

    def to_requests(
        self,
        intent: str,
        entities: dict[str, str] | None = None,
        context: dict[str, str] | None = None,
    ) -> list[ToolRequest]:
        payload_entities = entities or {}
        payload_context = context or {}
        return [
            ToolRequest(
                tool_name=tool_name,
                intent=intent,
                entities=payload_entities,
                context=payload_context,
            )
            for tool_name in self.selected_tools
        ]
