from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult, SuggestedAction
from app.models.tool import ToolSelectionResult
from app.models.tool_contracts import ToolRequest, ToolResult
from app.tools.selection import IRAN_POST_TRACKING, ORDER_LOOKUP, select_tools


def test_order_lookup_request_creation() -> None:
    intent_result = IntentClassificationResult(
        primary_intent=IntentId.ORDER_STATUS_INQUIRY,
        confidence=0.9,
        entities={"order_id": "INC-7342409"},
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )
    selection = select_tools(intent_result)
    requests = selection.to_requests(
        intent=intent_result.primary_intent.value,
        entities=intent_result.entities,
        context={"seller_message": "سفارش INC-7342409 کجاست؟"},
    )

    assert len(requests) == 1
    assert requests[0] == ToolRequest(
        tool_name=ORDER_LOOKUP,
        intent="order_status_inquiry",
        entities={"order_id": "INC-7342409"},
        context={"seller_message": "سفارش INC-7342409 کجاست؟"},
    )


def test_iran_post_tracking_request_creation() -> None:
    intent_result = IntentClassificationResult(
        primary_intent=IntentId.SHIPPING_INQUIRY,
        confidence=0.9,
        entities={"tracking_code": "1234567890"},
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )
    selection = select_tools(intent_result)
    requests = selection.to_requests(
        intent=intent_result.primary_intent.value,
        entities=intent_result.entities,
    )

    assert len(requests) == 1
    assert requests[0].tool_name == IRAN_POST_TRACKING
    assert requests[0].entities["tracking_code"] == "1234567890"


def test_tool_result_serialization() -> None:
    result = ToolResult(
        tool_name=ORDER_LOOKUP,
        success=True,
        data={"status": "shipped"},
        summary="Order is shipped.",
        error=None,
    )

    payload = result.model_dump()
    restored = ToolResult.model_validate(payload)

    assert restored.tool_name == ORDER_LOOKUP
    assert restored.success is True
    assert restored.data == {"status": "shipped"}
    assert restored.summary == "Order is shipped."
    assert restored.error is None


def test_empty_selection_produces_no_requests() -> None:
    selection = ToolSelectionResult(selected_tools=[])

    assert selection.to_requests(intent="general_inquiry", entities={}) == []
