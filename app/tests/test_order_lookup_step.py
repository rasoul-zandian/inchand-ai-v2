from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult, SuggestedAction
from app.models.tool import ToolSelectionResult
from app.models.tool_contracts import ToolRequest, ToolResult
from app.pipeline.order_lookup_step import MAX_ORDER_LOOKUPS, run_selected_order_lookup
from app.tools.order_lookup import ORDER_LOOKUP_TOOL


def _intent_result(**entities) -> IntentClassificationResult:
    return IntentClassificationResult(
        primary_intent=IntentId.ORDER_STATUS_INQUIRY,
        confidence=0.9,
        entities=entities,
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )


def _success_result(order_id: str) -> ToolResult:
    return ToolResult(
        tool_name=ORDER_LOOKUP_TOOL,
        success=True,
        data={"order_id": order_id, "found": "true"},
        summary="ok",
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
        return _success_result("INC-7342409")

    selection = ToolSelectionResult(selected_tools=[ORDER_LOOKUP_TOOL])
    intent = _intent_result(order_id="INC-7342409")

    result = run_selected_order_lookup(selection, intent, lookup_fn=fake_lookup)

    assert len(calls) == 1
    assert calls[0].tool_name == ORDER_LOOKUP_TOOL
    assert calls[0].entities["order_id"] == "INC-7342409"
    assert result.executed is True
    assert result.successful_count == 1


def test_multi_order_lookup_executes_each_id_in_order() -> None:
    calls: list[ToolRequest] = []

    def fake_lookup(request: ToolRequest) -> ToolResult:
        calls.append(request)
        return _success_result(request.entities["order_id"])

    result = run_selected_order_lookup(
        ToolSelectionResult(selected_tools=[ORDER_LOOKUP_TOOL]),
        _intent_result(order_ids=["INC-7338176", "INC-7337206"]),
        lookup_fn=fake_lookup,
    )

    assert [request.entities["order_id"] for request in calls] == [
        "INC-7338176",
        "INC-7337206",
    ]
    assert result.successful_count == 2
    assert result.failed_count == 0
    assert len(result.results) == 2


def test_multi_order_lookup_passes_shop_id_to_every_request() -> None:
    calls: list[ToolRequest] = []

    def fake_lookup(request: ToolRequest) -> ToolResult:
        calls.append(request)
        return _success_result(request.entities["order_id"])

    run_selected_order_lookup(
        ToolSelectionResult(selected_tools=[ORDER_LOOKUP_TOOL]),
        _intent_result(order_ids=["INC-7338176", "INC-7337206"]),
        context={"shop_id": "5456"},
        lookup_fn=fake_lookup,
    )

    assert all(request.context["shop_id"] == "5456" for request in calls)


def test_multi_order_lookup_truncates_at_max_and_warns() -> None:
    order_ids = [f"INC-{7338000 + index}" for index in range(12)]

    def fake_lookup(request: ToolRequest) -> ToolResult:
        return _success_result(request.entities["order_id"])

    result = run_selected_order_lookup(
        ToolSelectionResult(selected_tools=[ORDER_LOOKUP_TOOL]),
        _intent_result(order_ids=order_ids),
        lookup_fn=fake_lookup,
    )

    assert len(result.results) == MAX_ORDER_LOOKUPS
    assert result.truncated_count == 2
    assert "order_lookup_truncated" in result.warnings


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
    assert result.results == [expected]


def test_failure_tool_result_propagated() -> None:
    expected = ToolResult(
        tool_name=ORDER_LOOKUP_TOOL,
        success=False,
        summary="",
        error="order_lookup_failed",
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
    assert result.failed_count == 1
    assert result.successful_count == 0
