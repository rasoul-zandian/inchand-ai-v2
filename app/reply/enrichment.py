"""Enrich seller replies using order lookup and tracking results."""

from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult
from app.models.pipeline import OrderLookupExecutionResult
from app.models.reply import ReplyGenerationResult
from app.models.tool_contracts import ToolResult
from app.reply.templates import COMPLAINT_FOLLOWUP_REPLY
from app.tools.mahex_tracking import MAHEX_TRACKING_TOOL


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


def _build_delivery_confirmation_reply(data: dict[str, str]) -> str:
    order_id = data.get("order_id", "")
    order_status = data.get("order_status", "")
    parts = ["اطلاع شما درباره تحویل سفارش دریافت شد."]
    parts.append(f"وضعیت سفارش {order_id}: {order_status}.")

    parcel_status = data.get("primary_parcel_status_name", "")
    if parcel_status:
        parts.append(f"وضعیت مرسوله: {parcel_status}.")

    tracking_code = data.get("primary_parcel_tracking_code", "")
    if tracking_code and data.get("has_parcel_tracking_code", "").lower() == "true":
        parts.append(f"کد رهگیری: {tracking_code}.")

    return " ".join(parts)


def _build_multi_delivery_confirmation_reply(data_list: list[dict[str, str]]) -> str:
    blocks = [_build_status_reply(data) for data in data_list]
    return "اطلاع شما درباره تحویل سفارش‌ها دریافت شد.\n\n" + "\n\n".join(blocks)


def _build_multi_status_reply(data_list: list[dict[str, str]]) -> str:
    return "\n\n".join(_build_status_reply(data) for data in data_list)


def _lookup_results(
    order_lookup_execution_result: OrderLookupExecutionResult,
) -> list[ToolResult]:
    if order_lookup_execution_result.results:
        return order_lookup_execution_result.results
    if order_lookup_execution_result.tool_result is not None:
        return [order_lookup_execution_result.tool_result]
    return []


def _merge_warnings(
    reply_result: ReplyGenerationResult,
    order_lookup_execution_result: OrderLookupExecutionResult,
) -> list[str]:
    warnings = list(reply_result.warnings)
    for warning in order_lookup_execution_result.warnings:
        if warning not in warnings:
            warnings.append(warning)
    return warnings


def _build_mahex_tracking_reply(base_text: str, data: dict[str, str]) -> str:
    status_text = data.get("status_text") or data.get("current_state_name", "")
    parts = [base_text, f"وضعیت مرسوله ماهکس: {status_text}."]
    if data.get("delivered", "").lower() == "true":
        parts.append("مرسوله طبق اطلاعات ماهکس تحویل شده است.")
    return " ".join(part for part in parts if part)


def _successful_lookup_data(results: list[ToolResult]) -> list[dict[str, str]]:
    return [
        result.data
        for result in results
        if result.success and result.data.get("found") == "true"
    ]


def _apply_mahex_tracking(
    reply_result: ReplyGenerationResult,
    intent_result: IntentClassificationResult,
    tracking_result: ToolResult | None,
) -> ReplyGenerationResult:
    if tracking_result is None or tracking_result.tool_name != MAHEX_TRACKING_TOOL:
        return reply_result

    if not tracking_result.success or tracking_result.data.get("found") != "true":
        warnings = list(reply_result.warnings)
        if "mahex_tracking_failed" not in warnings:
            warnings.append("mahex_tracking_failed")
        return reply_result.model_copy(update={"warnings": warnings})

    if intent_result.primary_intent not in {
        IntentId.SHIPPING_INQUIRY,
        IntentId.DELIVERY_CONFIRMATION_REQUEST,
    }:
        return reply_result

    text = _build_mahex_tracking_reply(reply_result.text, tracking_result.data)
    return reply_result.model_copy(update={"text": text})


def enrich_reply_with_order_lookup(
    reply_result: ReplyGenerationResult,
    intent_result: IntentClassificationResult,
    order_lookup_execution_result: OrderLookupExecutionResult,
    *,
    tracking_result: ToolResult | None = None,
) -> ReplyGenerationResult:
    if not order_lookup_execution_result.executed:
        return _apply_mahex_tracking(reply_result, intent_result, tracking_result)

    warnings = _merge_warnings(reply_result, order_lookup_execution_result)
    results = _lookup_results(order_lookup_execution_result)
    successful_data = _successful_lookup_data(results)

    if results and not successful_data:
        if "order_lookup_failed" not in warnings:
            warnings.append("order_lookup_failed")
        current = reply_result.model_copy(update={"warnings": warnings})
        return _apply_mahex_tracking(current, intent_result, tracking_result)

    if results and len(successful_data) < len(results):
        if "order_lookup_partial_failure" not in warnings:
            warnings.append("order_lookup_partial_failure")

    if intent_result.primary_intent == IntentId.COMPLAINT_ORDER_FOLLOWUP:
        current = reply_result.model_copy(
            update={"text": COMPLAINT_FOLLOWUP_REPLY, "warnings": warnings}
        )
        return _apply_mahex_tracking(current, intent_result, tracking_result)

    if not successful_data:
        current = reply_result.model_copy(update={"warnings": warnings})
        return _apply_mahex_tracking(current, intent_result, tracking_result)

    if intent_result.primary_intent == IntentId.DELIVERY_CONFIRMATION_REQUEST:
        if len(successful_data) == 1:
            text = _build_delivery_confirmation_reply(successful_data[0])
        else:
            text = _build_multi_delivery_confirmation_reply(successful_data)
        current = reply_result.model_copy(update={"text": text, "warnings": warnings})
        return _apply_mahex_tracking(current, intent_result, tracking_result)

    if intent_result.primary_intent == IntentId.ORDER_STATUS_INQUIRY:
        if len(successful_data) == 1:
            data = successful_data[0]
            if _is_delivered(data):
                text = _build_delivered_reply(data.get("order_id", ""))
            else:
                text = _build_status_reply(data)
        else:
            text = _build_multi_status_reply(successful_data)
        current = reply_result.model_copy(update={"text": text, "warnings": warnings})
        return _apply_mahex_tracking(current, intent_result, tracking_result)

    current = reply_result
    if warnings != reply_result.warnings:
        current = current.model_copy(update={"warnings": warnings})
    return _apply_mahex_tracking(current, intent_result, tracking_result)
