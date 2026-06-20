from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult, SuggestedAction
from app.models.tool import ToolSelectionResult
from app.models.tool_contracts import ToolRequest, ToolResult
from app.pipeline.order_lookup_step import run_selected_order_lookup
from app.tools.order_lookup import ORDER_LOOKUP_TOOL


def _intent_result(**entities: str) -> IntentClassificationResult:
    return IntentClassificationResult(
        primary_intent=IntentId.ORDER_STATUS_INQUIRY,
        confidence=0.9,
        entities=entities,
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )


def test_empty_selected_tools_not_executed() -> None:
    result = run_selected_order_lookup(
        ToolSelectionResult(selected_tools=[]),
        _intent_result(order_id="INC-1"),
    )

    assert result.executed is False
    assert result.tool_result is None


def test_order_lookup_selected_calls_run_order_lookup_once() -> None:
    calls: list[ToolRequest] = []

    def fake_lookup(request: ToolRequest) -> ToolResult:
        calls.append(request)
        return ToolResult(
            tool_name=ORDER_LOOKUP_TOOL,
            success=True,
            data={"order_id": "INC-7342409", "found": "true"},
            summary="ok",
        )

    selection = ToolSelectionResult(selected_tools=[ORDER_LOOKUP_TOOL])
    intent = _intent_result(order_id="INC-7342409")

    result = run_selected_order_lookup(selection, intent, lookup_fn=fake_lookup)

    assert len(calls) == 1
    assert calls[0].tool_name == ORDER_LOOKUP_TOOL
    assert calls[0].entities["order_id"] == "INC-7342409"
    assert result.executed is True


def test_successful_tool_result_propagated() -> None:
    expected = ToolResult(
        tool_name=ORDER_LOOKUP_TOOL,
        success=True,
        data={"order_id": "INC-7342409", "found": "true", "order_status": "processing"},
        summary="Order INC-7342409 status is processing.",
    )

    def fake_lookup(_request: ToolRequest) -> ToolResult:
        return expected

    result = run_selected_order_lookup(
        ToolSelectionResult(selected_tools=[ORDER_LOOKUP_TOOL]),
        _intent_result(order_id="INC-7342409"),
        lookup_fn=fake_lookup,
    )

    assert result.executed is True
    assert result.tool_result == expected


def test_failure_tool_result_propagated() -> None:
    expected = ToolResult(
        tool_name=ORDER_LOOKUP_TOOL,
        success=False,
        summary="",
        error="missing_order_id",
    )

    def fake_lookup(_request: ToolRequest) -> ToolResult:
        return expected

    result = run_selected_order_lookup(
        ToolSelectionResult(selected_tools=[ORDER_LOOKUP_TOOL]),
        _intent_result(),
        lookup_fn=fake_lookup,
    )

    assert result.executed is True
    assert result.tool_result == expected
    assert result.tool_result.success is False
