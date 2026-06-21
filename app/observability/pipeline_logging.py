"""Minimal structured logging for pipeline runs."""

import json

from app.models.pipeline import PipelineResult

_METADATA_KEYS = ("case_id", "room_id", "message_id", "shop_id")


def _metadata_fields(metadata: dict | None) -> dict[str, str | None]:
    fields = {key: None for key in _METADATA_KEYS}
    if not metadata:
        return fields
    for key in _METADATA_KEYS:
        value = metadata.get(key)
        if value is not None:
            fields[key] = str(value)
    return fields


def build_pipeline_log_record(
    pipeline_result: PipelineResult,
    metadata: dict | None = None,
) -> dict:
    intent = pipeline_result.intent_result
    order_lookup = pipeline_result.order_lookup_result
    tool_result = order_lookup.tool_result

    order_lookup_success = None
    order_lookup_error = None
    if order_lookup.executed and tool_result is not None:
        order_lookup_success = tool_result.success
        order_lookup_error = tool_result.error

    record: dict = {
        "event": "pipeline_completed",
        **_metadata_fields(metadata),
        "primary_intent": intent.primary_intent.value,
        "confidence": intent.confidence,
        "suggested_action": intent.suggested_action.value,
        "needs_human_review": pipeline_result.needs_human_review,
        "entities": dict(intent.entities),
        "selected_tools": list(pipeline_result.tool_selection_result.selected_tools),
        "order_lookup_executed": order_lookup.executed,
        "order_lookup_success": order_lookup_success,
        "order_lookup_error": order_lookup_error,
        "final_reply_source": pipeline_result.final_reply.source,
        "final_reply_warnings": list(pipeline_result.final_reply.warnings),
    }
    if intent.fallback_reason is not None:
        record["fallback_reason"] = intent.fallback_reason
    return record


def emit_pipeline_log(record: dict) -> None:
    print(json.dumps(record, ensure_ascii=False))
