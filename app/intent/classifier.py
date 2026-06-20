"""Placeholder intent classifier (rule-backed until LLM integration)."""

from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult
from app.models.messages import ConversationMessage

_SETTLEMENT_MARKERS = ("تسویه", "settlement", "واریز")


def _normalize(text: str) -> str:
    return text.strip().lower()


def _combined_text(message: str, context: list[ConversationMessage] | None) -> str:
    parts = [_normalize(message)]
    if context:
        parts.extend(_normalize(msg.content) for msg in context)
    return " ".join(parts)


def classify_intent(
    message: str,
    conversation_context: list[ConversationMessage] | None = None,
) -> IntentClassificationResult:
    text = _normalize(message)
    settlement_context = any(
        marker in _combined_text(message, conversation_context)
        for marker in _SETTLEMENT_MARKERS
    )

    if "قرارداد" in text and ("تایید" in text or "شبا" in text or "iban" in text):
        return IntentClassificationResult(
            intent=IntentId.CONTRACT_APPROVAL,
            confidence=0.85,
            rationale="Message mentions contract approval after IBAN submission.",
            settlement_context=settlement_context,
        )

    if ("محصول" in text or "product" in text) and ("تایید" in text or "approval" in text):
        return IntentClassificationResult(
            intent=IntentId.PRODUCT_APPROVAL_REQUEST,
            confidence=0.85,
            rationale="Message requests product approval.",
            settlement_context=settlement_context,
        )

    if "آدرس" in text or "address" in text:
        return IntentClassificationResult(
            intent=IntentId.SHOP_ADDRESS_UPDATE,
            confidence=0.85,
            rationale="Message requests a shop address update.",
            settlement_context=settlement_context,
        )

    if any(k in text for k in ("شبا", "حساب", "بانک", "iban")):
        return IntentClassificationResult(
            intent=IntentId.BANK_ACCOUNT_CHANGE,
            confidence=0.85,
            rationale="Message requests bank account or IBAN update.",
            settlement_context=settlement_context,
        )

    if ("سفارش" in text or "order" in text) and ("ثبت" in text or "register" in text or "خطا" in text):
        return IntentClassificationResult(
            intent=IntentId.ORDER_REGISTRATION_ISSUE,
            confidence=0.85,
            rationale="Message reports an order registration problem.",
            settlement_context=settlement_context,
        )

    return IntentClassificationResult(
        intent=IntentId.ORDER_REGISTRATION_ISSUE,
        confidence=0.1,
        rationale="No rule matched; default fallback.",
        settlement_context=settlement_context,
    )
