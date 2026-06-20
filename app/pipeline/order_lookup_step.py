"""Run order_lookup when selected by tool selection."""

from typing import Callable

from app.models.intent import IntentClassificationResult
from app.models.pipeline import OrderLookupExecutionResult
from app.models.tool import ToolSelectionResult
from app.models.tool_contracts import ToolRequest, ToolResult
from app.tools.order_lookup import ORDER_LOOKUP_TOOL, run_order_lookup

LookupFn = Callable[[ToolRequest], ToolResult]


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

    caller = lookup_fn or run_order_lookup
    tool_result = caller(order_request)
    return OrderLookupExecutionResult(executed=True, tool_result=tool_result)
