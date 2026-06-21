from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.config import settings
from app.models.messages import ConversationMessage
from app.models.pipeline import PipelineResult
from app.pipeline.run_pipeline import run_pipeline

app = FastAPI(title=settings.app_name)


class PipelineMetadata(BaseModel):
    case_id: str | None = None
    room_id: str | None = None
    message_id: str | None = None
    shop_id: str | None = None


class PipelineRunRequest(BaseModel):
    seller_message: str = Field(min_length=1)
    conversation_context: list[ConversationMessage] = Field(default_factory=list)
    room_type: str | None = None
    metadata: PipelineMetadata | None = None


class ToolStatus(BaseModel):
    order_lookup_executed: bool
    order_lookup_success: bool | None
    order_lookup_error: str | None


class PipelineRunResponse(BaseModel):
    message_id: str | None = None
    room_id: str | None = None
    primary_intent: str
    confidence: float
    suggested_action: str
    needs_human_review: bool
    should_send: bool
    send_gated: bool
    final_reply: str
    final_reply_source: str
    entities: dict[str, str]
    selected_tools: list[str]
    tool_status: ToolStatus
    warnings: list[str]


def _build_response(
    result: PipelineResult,
    metadata: dict | None = None,
) -> PipelineRunResponse:
    order_lookup = result.order_lookup_result
    tool_result = order_lookup.tool_result
    order_lookup_success = None
    order_lookup_error = None
    if order_lookup.executed and tool_result is not None:
        order_lookup_success = tool_result.success
        order_lookup_error = tool_result.error

    send_gated = result.needs_human_review
    should_send = not result.needs_human_review
    final_reply_source = (
        "send_gate" if send_gated else result.final_reply.source
    )

    message_id = None
    room_id = None
    if metadata:
        if metadata.get("message_id") is not None:
            message_id = str(metadata["message_id"])
        if metadata.get("room_id") is not None:
            room_id = str(metadata["room_id"])

    return PipelineRunResponse(
        message_id=message_id,
        room_id=room_id,
        primary_intent=result.intent_result.primary_intent.value,
        confidence=result.intent_result.confidence,
        suggested_action=result.intent_result.suggested_action.value,
        needs_human_review=result.needs_human_review,
        should_send=should_send,
        send_gated=send_gated,
        final_reply=result.final_reply.text,
        final_reply_source=final_reply_source,
        entities=dict(result.intent_result.entities),
        selected_tools=list(result.tool_selection_result.selected_tools),
        tool_status=ToolStatus(
            order_lookup_executed=order_lookup.executed,
            order_lookup_success=order_lookup_success,
            order_lookup_error=order_lookup_error,
        ),
        warnings=list(result.final_reply.warnings),
    )


@app.post("/internal/pipeline/run", response_model=PipelineRunResponse)
def run_pipeline_endpoint(request: PipelineRunRequest) -> PipelineRunResponse:
    metadata = (
        request.metadata.model_dump(exclude_none=True) if request.metadata else None
    )
    result = run_pipeline(
        request.seller_message,
        conversation_context=request.conversation_context or None,
        room_type=request.room_type,
        metadata=metadata,
    )
    return _build_response(result, metadata)


def main() -> None:
    print(f"{settings.app_name} ready")


if __name__ == "__main__":
    main()
