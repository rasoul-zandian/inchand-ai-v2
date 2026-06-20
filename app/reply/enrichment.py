"""Enrich seller replies using order lookup results."""

from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult
from app.models.pipeline import OrderLookupExecutionResult
from app.models.reply import ReplyGenerationResult
from app.reply.templates import COMPLAINT_FOLLOWUP_REPLY


def _is_delivered(data: dict[str, str]) -> bool:
    if data.get("order_status") == "تحویل شده":
        return True
    return data.get("is_delivered_in_inchand", "").lower() == "true"


def _build_delivered_reply(order_id: str) -> str:
    return f"وضعیت سفارش {order_id} در وضعیت تحویل شده قرار دارد."


def _build_status_reply(data: dict[str, str]) -> str:
    order_id = data.get("order_id", "")
    order_status = data.get("order_status", "")
    parts = [f"وضعیت سفارش {order_id}: {order_status}."]

    parcel_status = data.get("primary_parcel_status_name", "")
    if parcel_status:
        parts.append(f"وضعیت مرسوله: {parcel_status}.")

    tracking_code = data.get("primary_parcel_tracking_code", "")
    if tracking_code and data.get("has_parcel_tracking_code", "").lower() == "true":
        parts.append(f"کد رهگیری: {tracking_code}.")

    return " ".join(parts)


def enrich_reply_with_order_lookup(
    reply_result: ReplyGenerationResult,
    intent_result: IntentClassificationResult,
    order_lookup_execution_result: OrderLookupExecutionResult,
) -> ReplyGenerationResult:
    if not order_lookup_execution_result.executed:
        return reply_result

    tool_result = order_lookup_execution_result.tool_result
    if tool_result is None or not tool_result.success:
        warnings = list(reply_result.warnings)
        if "order_lookup_failed" not in warnings:
            warnings.append("order_lookup_failed")
        return reply_result.model_copy(update={"warnings": warnings})

    if intent_result.primary_intent == IntentId.COMPLAINT_ORDER_FOLLOWUP:
        return reply_result.model_copy(update={"text": COMPLAINT_FOLLOWUP_REPLY})

    data = tool_result.data
    if data.get("found") != "true":
        return reply_result

    order_id = data.get("order_id", "")
    if _is_delivered(data):
        return reply_result.model_copy(update={"text": _build_delivered_reply(order_id)})

    if intent_result.primary_intent == IntentId.ORDER_STATUS_INQUIRY:
        return reply_result.model_copy(update={"text": _build_status_reply(data)})

    return reply_result
