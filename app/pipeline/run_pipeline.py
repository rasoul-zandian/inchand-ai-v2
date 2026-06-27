"""Minimal end-to-end seller support pipeline."""

from typing import Callable

from app.intent.classifier import classify_intent
from app.intent.taxonomy import IntentId
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
from app.reply.templates import DELIVERY_CONFIRMATION_MISSING_ORDER_ID_REPLY
from app.tools.selection import _has_order_entity, select_tools

LookupFn = Callable[[ToolRequest], ToolResult]

_HUMAN_REVIEW_ACKNOWLEDGEMENT = (
    "درخواست شما دریافت شد و جهت بررسی به کارشناسان مربوطه ارجاع شد."
)
_MISSING_ORDER_ID_FOR_DELIVERY_CONFIRMATION = (
    "missing_order_id_for_delivery_confirmation"
)


def _apply_delivery_confirmation_missing_order_gate(
    intent_result,
    reply_result: ReplyGenerationResult,
) -> tuple[object, ReplyGenerationResult, list[str]]:
    if intent_result.primary_intent != IntentId.DELIVERY_CONFIRMATION_REQUEST:
        return intent_result, reply_result, []
    if _has_order_entity(intent_result):
        return intent_result, reply_result, []

    updated_intent = intent_result.model_copy(
        update={"suggested_action": SuggestedAction.REQUEST_MISSING_INFORMATION}
    )
    updated_reply = reply_result.model_copy(
        update={
            "text": DELIVERY_CONFIRMATION_MISSING_ORDER_ID_REPLY,
            "suggested_action": SuggestedAction.REQUEST_MISSING_INFORMATION,
        }
    )
    return (
        updated_intent,
        updated_reply,
        [_MISSING_ORDER_ID_FOR_DELIVERY_CONFIRMATION],
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
    intent_result, current_reply, delivery_warnings = (
        _apply_delivery_confirmation_missing_order_gate(intent_result, current_reply)
    )
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
    if delivery_warnings:
        final_reply = final_reply.model_copy(
            update={"warnings": list(final_reply.warnings) + delivery_warnings}
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
