from pydantic import BaseModel, Field

from app.models.intent import IntentClassificationResult
from app.models.reply import (
    ReplyEvaluationResult,
    ReplyGenerationResult,
    ReplyRevisionResult,
)
from app.models.tool import ToolSelectionResult
from app.models.tool_contracts import ToolResult


class OrderLookupExecutionResult(BaseModel):
    executed: bool
    tool_result: ToolResult | None = None
    results: list[ToolResult] = Field(default_factory=list)
    successful_count: int = 0
    failed_count: int = 0
    truncated_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class PipelineResult(BaseModel):
    intent_result: IntentClassificationResult
    reply_result: ReplyGenerationResult
    evaluation_result: ReplyEvaluationResult
    revision_result: ReplyRevisionResult
    tool_selection_result: ToolSelectionResult
    order_lookup_result: OrderLookupExecutionResult
    final_reply: ReplyGenerationResult
    needs_human_review: bool = False
