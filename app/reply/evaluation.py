import re

from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult
from app.models.messages import ConversationMessage
from app.models.reply import ReplyEvaluationResult, ReplyGenerationResult
from app.reply.templates import FORBIDDEN_ONBOARDING_PHRASES, _entity_text_parts

_MAX_REPLY_LENGTH = 350
_BANK_DETAIL_MARKERS = ("شبا", "iban", "کارت", "card")
_DIGIT_SEQUENCE = re.compile(r"\d{10,}")
_IBAN_REQUEST_MARKERS = ("شبا", "حساب بانکی", "اطلاعات حساب")
_SELLER_FAILURE_MARKERS = ("نمیش", "نمی‌ش", "خطا", "مشکل", "ارور")
_REPLY_SUCCESS_CLAIMS = ("با موفقیت", "مشکلی ندارد", "انجام شده است")
_UNRELATED_QUESTION_MARKERS = ("شماره شبا", "آدرس فروشگاه", "محصولات خود را")


def _normalize(text: str) -> str:
    return text.strip().lower()


def _combined_seller_text(
    seller_message: str,
    conversation_context: list[ConversationMessage] | None,
) -> str:
    parts = [_normalize(seller_message)]
    if conversation_context:
        parts.extend(_normalize(msg.content) for msg in conversation_context if msg.role == "user")
    return " ".join(parts)


def _has_bank_details(text: str) -> bool:
    lowered = _normalize(text)
    if any(marker in lowered for marker in _BANK_DETAIL_MARKERS):
        return True
    return bool(_DIGIT_SEQUENCE.search(text))


def _asks_for_bank_details(reply_text: str) -> bool:
    lowered = _normalize(reply_text)
    return any(marker in lowered for marker in _IBAN_REQUEST_MARKERS) and (
        "ارسال" in lowered or "لطفاً" in lowered or "لطفا" in lowered
    )


def _mentions_any(reply_text: str, terms: tuple[str, ...]) -> bool:
    lowered = _normalize(reply_text)
    return any(term in lowered for term in terms)


def _append_issue(issues: list[str], code: str) -> None:
    if code not in issues:
        issues.append(code)


def _check_intent_alignment(
    intent_result: IntentClassificationResult,
    reply_result: ReplyGenerationResult,
    issues: list[str],
) -> None:
    if reply_result.primary_intent != intent_result.primary_intent:
        _append_issue(issues, "intent_mismatch")

    intent = intent_result.primary_intent
    reply_text = reply_result.text

    if intent == IntentId.BANK_ACCOUNT_CHANGE:
        seller_text = " ".join(intent_result.evidence + _entity_text_parts(intent_result))
        if _has_bank_details(seller_text) and _asks_for_bank_details(reply_text):
            _append_issue(issues, "requests_iban_already_provided")

    if intent == IntentId.COMPLAINT_ORDER_FOLLOWUP:
        if "؟" in reply_text:
            _append_issue(issues, "complaint_reply_asks_question")
        if _mentions_any(reply_text, _UNRELATED_QUESTION_MARKERS):
            _append_issue(issues, "complaint_reply_unrelated_request")
        if not _mentions_any(reply_text, ("ثبت", "بررسی")):
            _append_issue(issues, "complaint_reply_not_neutral_ack")

    if intent == IntentId.SHOP_ADDRESS_UPDATE:
        if not _mentions_any(reply_text, ("آدرس",)):
            _append_issue(issues, "shop_address_not_mentioned")

    if intent == IntentId.PRODUCT_APPROVAL_REQUEST:
        if not _mentions_any(reply_text, ("محصول", "تأیید", "تایید")):
            _append_issue(issues, "product_approval_not_mentioned")

    if intent == IntentId.SETTLEMENT_INQUIRY:
        if not _mentions_any(reply_text, ("تسویه",)):
            _append_issue(issues, "settlement_not_mentioned")


def evaluate_reply(
    seller_message: str,
    intent_result: IntentClassificationResult,
    reply_result: ReplyGenerationResult,
    conversation_context: list[ConversationMessage] | None = None,
) -> ReplyEvaluationResult:
    issues: list[str] = []
    reply_text = reply_result.text
    seller_text = _combined_seller_text(seller_message, conversation_context)

    _check_intent_alignment(intent_result, reply_result, issues)

    if len(reply_text) > _MAX_REPLY_LENGTH:
        _append_issue(issues, "too_verbose")

    for phrase in FORBIDDEN_ONBOARDING_PHRASES:
        if phrase in reply_text:
            _append_issue(issues, f"forbidden_onboarding:{phrase}")

    if intent_result.primary_intent == IntentId.BANK_ACCOUNT_CHANGE:
        provided = _has_bank_details(seller_text) or _has_bank_details(
            " ".join(intent_result.evidence + _entity_text_parts(intent_result))
        )
        if provided and _asks_for_bank_details(reply_text):
            _append_issue(issues, "requests_iban_already_provided")

    if any(marker in seller_text for marker in _SELLER_FAILURE_MARKERS) and any(
        claim in reply_text for claim in _REPLY_SUCCESS_CLAIMS
    ):
        _append_issue(issues, "contradicts_seller")

    score = 1.0 if not issues else max(0.0, 1.0 - (0.2 * len(issues)))
    return ReplyEvaluationResult(passed=len(issues) == 0, score=score, issues=issues)
