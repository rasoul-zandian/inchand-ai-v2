from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult, SuggestedAction
from app.tools.selection import ORDER_LOOKUP, IRAN_POST_TRACKING, PRODUCT_LOOKUP, select_tools


def _intent(intent_id: IntentId, **entities: str) -> IntentClassificationResult:
    return IntentClassificationResult(
        primary_intent=intent_id,
        confidence=0.9,
        entities=entities,
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )


def test_order_inquiry_with_order_id_selects_order_lookup() -> None:
    result = select_tools(_intent(IntentId.ORDER_STATUS_INQUIRY, order_id="INC-7342409"))

    assert result.selected_tools == [ORDER_LOOKUP]
    assert not result.requires_human_followup


def test_shipping_with_tracking_code_selects_iran_post_tracking() -> None:
    result = select_tools(_intent(IntentId.SHIPPING_INQUIRY, tracking_code="1234567890"))

    assert result.selected_tools == [IRAN_POST_TRACKING]
    assert not result.requires_human_followup


def test_shipping_with_order_id_without_tracking_selects_order_lookup() -> None:
    result = select_tools(_intent(IntentId.SHIPPING_INQUIRY, order_id="INC-7342409"))

    assert result.selected_tools == [ORDER_LOOKUP]
    assert IRAN_POST_TRACKING not in result.selected_tools
    assert any(item["tool"] == IRAN_POST_TRACKING for item in result.skipped_tools)


def test_product_approval_without_product_id_requires_human_followup() -> None:
    result = select_tools(_intent(IntentId.PRODUCT_APPROVAL_REQUEST))

    assert result.selected_tools == []
    assert result.requires_human_followup
    assert any(item["tool"] == PRODUCT_LOOKUP for item in result.skipped_tools)


def test_bank_account_change_selects_no_tool_and_requires_human_followup() -> None:
    result = select_tools(_intent(IntentId.BANK_ACCOUNT_CHANGE))

    assert result.selected_tools == []
    assert result.requires_human_followup


def test_complaint_followup_with_order_id_selects_order_lookup() -> None:
    result = select_tools(_intent(IntentId.COMPLAINT_ORDER_FOLLOWUP, order_id="INC-7342409"))

    assert result.selected_tools == [ORDER_LOOKUP]
    assert not result.requires_human_followup


def test_delivery_confirmation_with_order_id_selects_order_lookup() -> None:
    result = select_tools(
        _intent(IntentId.DELIVERY_CONFIRMATION_REQUEST, order_id="INC-7338176")
    )

    assert result.selected_tools == [ORDER_LOOKUP]
    assert not result.requires_human_followup


def test_delivery_confirmation_with_order_ids_selects_order_lookup() -> None:
    result = select_tools(
        _intent(
            IntentId.DELIVERY_CONFIRMATION_REQUEST,
            order_ids="INC-7338176,INC-7337206",
        )
    )

    assert result.selected_tools == [ORDER_LOOKUP]
    assert not result.requires_human_followup
