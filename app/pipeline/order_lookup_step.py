"""Run order_lookup when selected by tool selection."""

from typing import Callable

from app.models.intent import IntentClassificationResult
from app.models.pipeline import OrderLookupExecutionResult
from app.models.tool import ToolSelectionResult
from app.models.tool_contracts import ToolRequest, ToolResult
from app.tools.order_lookup import ORDER_LOOKUP_TOOL, _normalize_order_id, run_order_lookup

LookupFn = Callable[[ToolRequest], ToolResult]

MAX_ORDER_LOOKUPS = 10


def _order_ids_from_entities(entities: dict[str, str | list[str]]) -> list[str]:
    order_ids = entities.get("order_ids")
    if isinstance(order_ids, list):
        normalized = [
            _normalize_order_id(str(item))
            for item in order_ids
            if str(item).strip()
        ]
        if normalized:
            return list(dict.fromkeys(normalized))

    order_id = entities.get("order_id")
    if isinstance(order_id, str) and order_id.strip():
        return [_normalize_order_id(order_id)]

    return []


def _is_successful_lookup(result: ToolResult) -> bool:
    return result.success and result.data.get("found") == "true"


def run_selected_order_lookup(
    tool_selection_result: ToolSelectionResult,
    intent_result: IntentClassificationResult,
    context: dict[str, str] | None = None,
    *,
    lookup_fn: LookupFn | None = None,
) -> OrderLookupExecutionResult:
    if ORDER_LOOKUP_TOOL not in tool_selection_result.selected_tools:
        return OrderLookupExecutionResult(executed=False, tool_result=None)

    requests = tool_selection_result.to_requests(
        intent=intent_result.primary_intent.value,
        entities=intent_result.entities,
        context=context or {},
    )
    order_request = next(
        (request for request in requests if request.tool_name == ORDER_LOOKUP_TOOL),
        None,
    )
    if order_request is None:
        return OrderLookupExecutionResult(executed=False, tool_result=None)

    order_ids = _order_ids_from_entities(order_request.entities)
    if not order_ids:
        return OrderLookupExecutionResult(executed=False, tool_result=None)

    truncated_count = max(0, len(order_ids) - MAX_ORDER_LOOKUPS)
    lookup_ids = order_ids[:MAX_ORDER_LOOKUPS]

    caller = lookup_fn or run_order_lookup
    results: list[ToolResult] = []
    for order_id in lookup_ids:
        single_request = ToolRequest(
            tool_name=ORDER_LOOKUP_TOOL,
            intent=order_request.intent,
            entities={"order_id": order_id},
            context=dict(order_request.context),
        )
        results.append(caller(single_request))

    warnings: list[str] = []
    if truncated_count > 0:
        warnings.append("order_lookup_truncated")

    successful_count = sum(1 for result in results if _is_successful_lookup(result))
    failed_count = len(results) - successful_count

    return OrderLookupExecutionResult(
        executed=True,
        tool_result=results[0] if results else None,
        results=results,
        successful_count=successful_count,
        failed_count=failed_count,
        truncated_count=truncated_count,
        warnings=warnings,
    )
