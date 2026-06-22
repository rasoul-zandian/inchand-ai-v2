"""Tool selection based on intent and entities."""

from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult
from app.models.messages import ConversationMessage
from app.models.tool import ToolSelectionResult

ORDER_LOOKUP = "order_lookup"
IRAN_POST_TRACKING = "iran_post_tracking"
PRODUCT_LOOKUP = "product_lookup"
SHOP_LOOKUP = "shop_lookup"

_ORDER_INTENTS = {
    IntentId.ORDER_STATUS_INQUIRY,
    IntentId.ORDER_CANCELLATION,
    IntentId.COMPLAINT_ORDER_FOLLOWUP,
}
_PRODUCT_INTENTS = {
    IntentId.PRODUCT_APPROVAL_REQUEST,
    IntentId.PRODUCT_REJECTION_INQUIRY,
    IntentId.PRODUCT_EDIT_REQUEST,
}
_HUMAN_ONLY_INTENTS = {
    IntentId.SHOP_ADDRESS_UPDATE,
    IntentId.SHOP_PROFILE_UPDATE,
    IntentId.BANK_ACCOUNT_CHANGE,
    IntentId.CARD_CHANGE_REQUEST,
    IntentId.CONTRACT_APPROVAL,
    IntentId.SETTLEMENT_INQUIRY,
    IntentId.DOCUMENT_SUBMISSION,
    IntentId.ACCOUNT_ACCESS_ISSUE,
    IntentId.COMMISSION_INQUIRY,
    IntentId.TECHNICAL_BUG_REPORT,
}


def _entity(intent_result: IntentClassificationResult, *keys: str) -> str | None:
    for key in keys:
        value = intent_result.entities.get(key)
        if value and value.strip():
            return value.strip()
    return None


def _has_order_entity(intent_result: IntentClassificationResult) -> bool:
    return _entity(intent_result, "order_id", "order_ids") is not None


def _skip(tool: str, reason: str) -> dict[str, str]:
    return {"tool": tool, "reason": reason}


def select_tools(
    intent_result: IntentClassificationResult,
    conversation_context: list[ConversationMessage] | None = None,
) -> ToolSelectionResult:
    del conversation_context

    intent = intent_result.primary_intent
    order_id = _entity(intent_result, "order_id")
    tracking_code = _entity(intent_result, "tracking_code")
    product_id = _entity(intent_result, "product_id")

    selected: list[str] = []
    skipped: list[dict[str, str]] = []
    requires_human = False
    reason = ""

    if intent in _ORDER_INTENTS:
        if order_id:
            selected.append(ORDER_LOOKUP)
            reason = "order_id present for order-related intent"
        else:
            skipped.append(_skip(ORDER_LOOKUP, "order_id_missing"))
            requires_human = True
            reason = "order_id missing for order-related intent"

    elif intent == IntentId.SHIPPING_INQUIRY:
        if tracking_code:
            selected.append(IRAN_POST_TRACKING)
            reason = "tracking_code present for shipping inquiry"
        elif order_id:
            selected.append(ORDER_LOOKUP)
            reason = "order_id present; tracking_code missing"
            skipped.append(_skip(IRAN_POST_TRACKING, "tracking_code_missing"))
        else:
            skipped.append(_skip(IRAN_POST_TRACKING, "tracking_code_missing"))
            skipped.append(_skip(ORDER_LOOKUP, "order_id_missing"))
            requires_human = True
            reason = "tracking_code and order_id missing for shipping inquiry"

    elif intent in _PRODUCT_INTENTS:
        if product_id:
            selected.append(PRODUCT_LOOKUP)
            reason = "product_id present for product-related intent"
        else:
            skipped.append(_skip(PRODUCT_LOOKUP, "product_id_missing"))
            requires_human = True
            reason = "product_id missing for product-related intent"

    elif intent == IntentId.DELIVERY_CONFIRMATION_REQUEST:
        if _has_order_entity(intent_result):
            selected.append(ORDER_LOOKUP)
            reason = "order_id present for delivery confirmation"
        else:
            reason = "no order_id for delivery confirmation"

    elif intent in _HUMAN_ONLY_INTENTS:
        requires_human = True
        reason = f"no read-only tool configured for {intent.value}"

    elif intent == IntentId.GENERAL_INQUIRY:
        requires_human = True
        reason = "general inquiry requires human followup"

    else:
        reason = f"no tool selection rule for {intent.value}"

    return ToolSelectionResult(
        selected_tools=selected,
        skipped_tools=skipped,
        reason=reason,
        requires_human_followup=requires_human,
    )
