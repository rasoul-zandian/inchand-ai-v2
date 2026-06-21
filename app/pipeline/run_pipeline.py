"""Minimal end-to-end seller support pipeline."""

from typing import Callable

from app.intent.classifier import classify_intent
from app.models.intent import SuggestedAction
from app.models.messages import ConversationMessage
from app.models.pipeline import PipelineResult
from app.models.reply import ReplyGenerationResult
from app.models.tool_contracts import ToolRequest, ToolResult
from app.observability.pipeline_logging import build_pipeline_log_record, emit_pipeline_log
from app.pipeline.order_lookup_step import run_selected_order_lookup
from app.reply.enrichment import enrich_reply_with_order_lookup
from app.reply.evaluation import evaluate_reply
from app.reply.generator import generate_reply
from app.reply.revision import revise_reply
from app.tools.selection import select_tools

LookupFn = Callable[[ToolRequest], ToolResult]

_HUMAN_REVIEW_ACKNOWLEDGEMENT = (
    "درخواست شما دریافت شد و جهت بررسی به کارشناسان مربوطه ارجاع شد."
)


def _apply_send_gate(
    final_reply: ReplyGenerationResult,
    suggested_action: SuggestedAction,
) -> tuple[ReplyGenerationResult, bool]:
    if suggested_action in {SuggestedAction.HUMAN_FOLLOWUP, SuggestedAction.ESCALATE}:
        return (
            final_reply.model_copy(update={"text": _HUMAN_REVIEW_ACKNOWLEDGEMENT}),
            True,
        )
    return final_reply, False


def _tool_context(
    seller_message: str,
    conversation_context: list[ConversationMessage] | None,
    shop_id: str | None = None,
) -> dict[str, str]:
    context = {"seller_message": seller_message}
    if shop_id:
        context["shop_id"] = shop_id
    if conversation_context:
        for index, message in enumerate(conversation_context):
            context[f"{message.role}_{index}"] = message.content
    return context


def run_pipeline(
    seller_message: str,
    conversation_context: list[ConversationMessage] | None = None,
    room_type: str | None = None,
    metadata: dict | None = None,
    *,
    lookup_fn: LookupFn | None = None,
) -> PipelineResult:
    intent_result = classify_intent(
        seller_message,
        conversation_context=conversation_context,
        room_type=room_type,
    )
    reply_result = generate_reply(intent_result, conversation_context=conversation_context)
    evaluation_result = evaluate_reply(
        seller_message,
        intent_result,
        reply_result,
        conversation_context=conversation_context,
    )
    revision_result = revise_reply(
        seller_message,
        intent_result,
        reply_result,
        evaluation_result,
    )

    if evaluation_result.passed:
        current_reply = reply_result
    else:
        current_reply = reply_result.model_copy(update={"text": revision_result.revised_text})

    tool_selection_result = select_tools(intent_result, conversation_context=conversation_context)
    shop_id = None
    if metadata and metadata.get("shop_id") is not None:
        shop_id = str(metadata["shop_id"])
    order_lookup_result = run_selected_order_lookup(
        tool_selection_result,
        intent_result,
        context=_tool_context(seller_message, conversation_context, shop_id=shop_id),
        lookup_fn=lookup_fn,
    )
    final_reply = enrich_reply_with_order_lookup(
        current_reply,
        intent_result,
        order_lookup_result,
    )
    final_reply, needs_human_review = _apply_send_gate(
        final_reply,
        intent_result.suggested_action,
    )

    result = PipelineResult(
        intent_result=intent_result,
        reply_result=reply_result,
        evaluation_result=evaluation_result,
        revision_result=revision_result,
        tool_selection_result=tool_selection_result,
        order_lookup_result=order_lookup_result,
        final_reply=final_reply,
        needs_human_review=needs_human_review,
    )
    emit_pipeline_log(build_pipeline_log_record(result, metadata))
    return result
