"""Intent classifier with rule-backed default and optional OpenAI provider."""

from app.config import settings
from app.intent.llm_classifier import try_classify_intent_with_openai
from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult, SuggestedAction
from app.models.messages import ConversationMessage

_SETTLEMENT_MARKERS = ("تسویه", "settlement", "واریز")
_BANK_MARKERS = ("شبا", "حساب", "بانک", "iban")
_CARD_MARKERS = ("کارت", "card")
_ORDER_MARKERS = ("سفارش", "order")
_PRODUCT_MARKERS = ("محصول", "product")
_COMPLAINT_CONTEXT_MARKERS = ("شکایت", "complaint")
_COMPLAINT_RESOLUTION_MARKERS = ("تماس", "برگشت", "قرار شد", "جایگزین", "refund", "return")
_BUYER_REFUND_PHRASES = ("حسابشون", "حساب مشتری", "به حسابش")

_DEFAULT_ACTIONS: dict[IntentId, SuggestedAction] = {
    IntentId.ORDER_REGISTRATION_ISSUE: SuggestedAction.ESCALATE,
    IntentId.ORDER_STATUS_INQUIRY: SuggestedAction.REPLY_TO_SELLER,
    IntentId.ORDER_CANCELLATION: SuggestedAction.HUMAN_FOLLOWUP,
    IntentId.PRODUCT_APPROVAL_REQUEST: SuggestedAction.HUMAN_FOLLOWUP,
    IntentId.PRODUCT_REJECTION_INQUIRY: SuggestedAction.REPLY_TO_SELLER,
    IntentId.PRODUCT_EDIT_REQUEST: SuggestedAction.REPLY_TO_SELLER,
    IntentId.SHOP_ADDRESS_UPDATE: SuggestedAction.REQUEST_MISSING_INFORMATION,
    IntentId.SHOP_PROFILE_UPDATE: SuggestedAction.REQUEST_MISSING_INFORMATION,
    IntentId.BANK_ACCOUNT_CHANGE: SuggestedAction.REQUEST_MISSING_INFORMATION,
    IntentId.CARD_CHANGE_REQUEST: SuggestedAction.REQUEST_MISSING_INFORMATION,
    IntentId.CONTRACT_APPROVAL: SuggestedAction.HUMAN_FOLLOWUP,
    IntentId.SETTLEMENT_INQUIRY: SuggestedAction.REPLY_TO_SELLER,
    IntentId.DOCUMENT_SUBMISSION: SuggestedAction.REPLY_TO_SELLER,
    IntentId.ACCOUNT_ACCESS_ISSUE: SuggestedAction.ESCALATE,
    IntentId.COMMISSION_INQUIRY: SuggestedAction.REPLY_TO_SELLER,
    IntentId.SHIPPING_INQUIRY: SuggestedAction.REPLY_TO_SELLER,
    IntentId.RETURN_REFUND_INQUIRY: SuggestedAction.REPLY_TO_SELLER,
    IntentId.COMPLAINT_ORDER_FOLLOWUP: SuggestedAction.HUMAN_FOLLOWUP,
    IntentId.TECHNICAL_BUG_REPORT: SuggestedAction.ESCALATE,
    IntentId.GENERAL_INQUIRY: SuggestedAction.REPLY_TO_SELLER,
}


def _normalize(text: str) -> str:
    return text.strip().lower()


def _combined_text(message: str, context: list[ConversationMessage] | None) -> str:
    parts = [_normalize(message)]
    if context:
        parts.extend(_normalize(msg.content) for msg in context)
    return " ".join(parts)


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _context_text(context: list[ConversationMessage] | None) -> str:
    if not context:
        return ""
    return " ".join(_normalize(msg.content) for msg in context)


def _has_complaint_context(context: list[ConversationMessage] | None) -> bool:
    text = _context_text(context)
    return _has_any(text, _COMPLAINT_CONTEXT_MARKERS) or "inc-" in text


def _has_complaint_resolution(text: str) -> bool:
    return _has_any(text, _COMPLAINT_RESOLUTION_MARKERS)


def _has_bank_change_context(text: str) -> bool:
    if _has_any(text, ("شبا", "iban", "بانک")):
        return True
    if "حساب" not in text:
        return False
    if _has_any(text, _BUYER_REFUND_PHRASES):
        return False
    return True


def _bank_card_settlement_result(
    text: str,
    *,
    context_flags: list[str],
    bank_change: bool,
    card_change: bool,
) -> IntentClassificationResult:
    flags = list(context_flags)
    negative: list[IntentId] = []
    if settlement_context := "settlement_context" in context_flags:
        negative.append(IntentId.SETTLEMENT_INQUIRY)

    if bank_change and card_change:
        flags.append("card_provided")
        evidence = [m for m in _BANK_MARKERS + _CARD_MARKERS if m in text]
        if settlement_context:
            evidence.append("تسویه")
        return _build_result(
            IntentId.BANK_ACCOUNT_CHANGE,
            0.85,
            evidence,
            context_flags=flags,
            negative_intents=negative,
        )

    primary = IntentId.BANK_ACCOUNT_CHANGE if bank_change else IntentId.CARD_CHANGE_REQUEST
    evidence = [m for m in _BANK_MARKERS + _CARD_MARKERS if m in text]
    if settlement_context:
        evidence.append("تسویه")
    return _build_result(
        primary,
        0.85,
        evidence,
        context_flags=flags,
        negative_intents=negative,
    )


def _build_result(
    primary_intent: IntentId,
    confidence: float,
    evidence: list[str],
    *,
    context_flags: list[str] | None = None,
    negative_intents: list[IntentId] | None = None,
    entities: dict[str, str] | None = None,
    suggested_action: SuggestedAction | None = None,
    fallback_reason: str | None = None,
) -> IntentClassificationResult:
    return IntentClassificationResult(
        primary_intent=primary_intent,
        confidence=confidence,
        evidence=evidence,
        entities=entities or {},
        context_flags=context_flags or [],
        negative_intents=negative_intents or [],
        suggested_action=suggested_action or _DEFAULT_ACTIONS[primary_intent],
        fallback_reason=fallback_reason,
    )


def _has_contract_reference(text: str) -> bool:
    return "قرارداد" in text or "قرار داد" in text


def classify_intent_with_rules(
    message: str,
    conversation_context: list[ConversationMessage] | None = None,
) -> IntentClassificationResult:
    text = _normalize(message)
    combined = _combined_text(message, conversation_context)
    settlement_context = _has_any(combined, _SETTLEMENT_MARKERS)
    context_flags = ["settlement_context"] if settlement_context else []

    if _has_contract_reference(combined) and _has_any(
        combined, ("تایید", "شبا", "iban")
    ):
        return _build_result(
            IntentId.CONTRACT_APPROVAL,
            0.85,
            ["قرارداد", "تایید/شبا"],
            context_flags=context_flags,
        )

    if conversation_context and _has_complaint_context(
        conversation_context
    ) and _has_complaint_resolution(text):
        return _build_result(
            IntentId.COMPLAINT_ORDER_FOLLOWUP,
            0.85,
            ["شکایت", "پیگیری/برگشت"],
            context_flags=context_flags,
        )

    bank_change = _has_bank_change_context(text)
    card_change = _has_any(text, _CARD_MARKERS)
    if settlement_context and (bank_change or card_change):
        return _bank_card_settlement_result(
            text,
            context_flags=context_flags,
            bank_change=bank_change,
            card_change=card_change,
        )

    if settlement_context and not bank_change and not card_change:
        return _build_result(
            IntentId.SETTLEMENT_INQUIRY,
            0.85,
            ["تسویه"],
            context_flags=context_flags,
        )

    if _has_any(text, _PRODUCT_MARKERS) and ("رد" in text or "rejected" in text):
        return _build_result(
            IntentId.PRODUCT_REJECTION_INQUIRY,
            0.85,
            ["محصول", "رد"],
            context_flags=context_flags,
        )

    if _has_any(text, _PRODUCT_MARKERS) and _has_any(
        text, ("تایید", "approval", "بررسی", "رسیدگی")
    ):
        return _build_result(
            IntentId.PRODUCT_APPROVAL_REQUEST,
            0.85,
            ["محصول", "تایید/بررسی"],
            context_flags=context_flags,
        )

    if _has_any(text, _PRODUCT_MARKERS) and _has_any(text, ("قیمت", "ویرایش", "edit", "price")):
        return _build_result(
            IntentId.PRODUCT_EDIT_REQUEST,
            0.85,
            ["محصول", "ویرایش/قیمت"],
            context_flags=context_flags,
        )

    if "آدرس" in text or "address" in text:
        return _build_result(
            IntentId.SHOP_ADDRESS_UPDATE,
            0.85,
            ["آدرس"],
            context_flags=context_flags,
        )

    if _has_any(text, ("نام فروشگاه", "تلفن", "phone", "shop name")):
        return _build_result(
            IntentId.SHOP_PROFILE_UPDATE,
            0.85,
            ["اطلاعات فروشگاه"],
            context_flags=context_flags,
        )

    if bank_change and card_change:
        flags = list(context_flags)
        flags.append("card_provided")
        return _build_result(
            IntentId.BANK_ACCOUNT_CHANGE,
            0.85,
            [m for m in _BANK_MARKERS + _CARD_MARKERS if m in text],
            context_flags=flags,
        )

    if card_change:
        return _build_result(
            IntentId.CARD_CHANGE_REQUEST,
            0.85,
            ["کارت"],
            context_flags=context_flags,
        )

    if bank_change:
        return _build_result(
            IntentId.BANK_ACCOUNT_CHANGE,
            0.85,
            [m for m in _BANK_MARKERS if m in text],
            context_flags=context_flags,
        )

    if _has_any(text, _ORDER_MARKERS) and _has_any(text, ("لغو", "کنسل", "cancel")):
        return _build_result(
            IntentId.ORDER_CANCELLATION,
            0.85,
            ["سفارش", "لغو"],
            context_flags=context_flags,
        )

    if _has_any(text, _ORDER_MARKERS) and _has_any(text, ("وضعیت", "پیگیری", "status", "track")):
        return _build_result(
            IntentId.ORDER_STATUS_INQUIRY,
            0.85,
            ["سفارش", "وضعیت/پیگیری"],
            context_flags=context_flags,
        )

    if _has_any(text, _ORDER_MARKERS) and _has_any(text, ("ثبت", "register", "خطا", "error")):
        return _build_result(
            IntentId.ORDER_REGISTRATION_ISSUE,
            0.85,
            ["سفارش", "ثبت/خطا"],
            context_flags=context_flags,
        )

    if _has_any(text, ("مدارک", "آپلود", "upload", "document")):
        return _build_result(
            IntentId.DOCUMENT_SUBMISSION,
            0.85,
            ["مدارک"],
            context_flags=context_flags,
        )

    if _has_any(text, ("ورود", "رمز", "login", "password")):
        return _build_result(
            IntentId.ACCOUNT_ACCESS_ISSUE,
            0.85,
            ["دسترسی/رمز"],
            context_flags=context_flags,
        )

    if _has_any(text, ("کارمزد", "commission", "fee")):
        return _build_result(
            IntentId.COMMISSION_INQUIRY,
            0.85,
            ["کارمزد"],
            context_flags=context_flags,
        )

    if _has_any(text, ("ارسال", "پست", "shipping", "delivery")):
        return _build_result(
            IntentId.SHIPPING_INQUIRY,
            0.85,
            ["ارسال"],
            context_flags=context_flags,
        )

    if _has_any(text, ("مرجوعی", "استرداد", "refund", "return")):
        return _build_result(
            IntentId.RETURN_REFUND_INQUIRY,
            0.85,
            ["مرجوعی/استرداد"],
            context_flags=context_flags,
        )

    if _has_any(text, ("باگ", "کرش", "crash", "bug")):
        return _build_result(
            IntentId.TECHNICAL_BUG_REPORT,
            0.85,
            ["باگ/کرش"],
            context_flags=context_flags,
        )

    return _build_result(
        IntentId.GENERAL_INQUIRY,
        0.1,
        ["fallback"],
        context_flags=context_flags,
    )


def classify_intent(
    message: str,
    conversation_context: list[ConversationMessage] | None = None,
) -> IntentClassificationResult:
    if settings.intent_classifier_provider == "openai":
        llm_result, fallback_reason = try_classify_intent_with_openai(
            message,
            conversation_context,
        )
        if llm_result is not None:
            return llm_result

        rule_result = classify_intent_with_rules(message, conversation_context)
        return rule_result.model_copy(update={"fallback_reason": fallback_reason})

    return classify_intent_with_rules(message, conversation_context)
