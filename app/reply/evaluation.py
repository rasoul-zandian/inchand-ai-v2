"""Rule-based reply quality evaluation."""

from __future__ import annotations

import re

from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult
from app.models.messages import ConversationMessage
from app.models.reply import ReplyEvaluationResult, ReplyGenerationResult
from app.reply.templates import FORBIDDEN_ONBOARDING_PHRASES

_MAX_REPLY_LENGTH = 180
_IBAN_REQUEST_PHRASES = ("لطفاً شماره شبا", "شماره شبا یا اطلاعات حساب")
_UNRELATED_QUESTION_PHRASES = (
    "لطفاً شماره شبا",
    "موضوع درخواست خود را دقیق‌تر",
    "راه‌اندازی فروشگاه",
    "تکمیل قرارداد",
)
_BANK_DETAIL_MARKERS = ("شبا", "iban", "کارت", "card")
_DIGIT_SEQUENCE = re.compile(r"\d{10,}")


def _combined_seller_text(
    seller_message: str,
    conversation_context: list[ConversationMessage] | None,
) -> str:
    parts = [seller_message]
    if conversation_context:
        parts.extend(msg.content for msg in conversation_context if msg.role == "user")
    return " ".join(parts)


def _seller_provided_bank_details(
    seller_message: str,
    conversation_context: list[ConversationMessage] | None,
) -> bool:
    text = _combined_seller_text(seller_message, conversation_context).lower()
    if any(marker in text for marker in _BANK_DETAIL_MARKERS):
        return True
    return bool(_DIGIT_SEQUENCE.search(text))


def _check_intent_match(
    intent_result: IntentClassificationResult,
    reply_result: ReplyGenerationResult,
    issues: list[str],
) -> bool:
    text = reply_result.text
    intent = intent_result.primary_intent

    if intent == IntentId.ORDER_REGISTRATION_ISSUE:
        ok = "سفارش" in text and "ثبت" in text
    elif intent == IntentId.PRODUCT_APPROVAL_REQUEST:
        ok = "محصول" in text and ("تأیید" in text or "تایید" in text or "بررسی" in text)
    elif intent == IntentId.SHOP_ADDRESS_UPDATE:
        ok = "آدرس" in text
    elif intent == IntentId.BANK_ACCOUNT_CHANGE:
        ok = "حساب" in text or "بانک" in text or "شبا" in text
    elif intent == IntentId.CARD_CHANGE_REQUEST:
        ok = "کارت" in text
    elif intent == IntentId.CONTRACT_APPROVAL:
        ok = "قرارداد" in text
    elif intent == IntentId.SETTLEMENT_INQUIRY:
        ok = "تسویه" in text
    elif intent == IntentId.COMPLAINT_ORDER_FOLLOWUP:
        ok = "ثبت" in text and "بررسی" in text
    elif intent == IntentId.GENERAL_INQUIRY:
        ok = "توضیح" in text
    else:
        ok = "ثبت" in text and "بررسی" in text

    if not ok:
        issues.append("intent_mismatch")
    return ok


def _check_no_redundant_request(
    seller_message: str,
    intent_result: IntentClassificationResult,
    reply_result: ReplyGenerationResult,
    conversation_context: list[ConversationMessage] | None,
    issues: list[str],
) -> bool:
    if intent_result.primary_intent not in (
        IntentId.BANK_ACCOUNT_CHANGE,
        IntentId.CARD_CHANGE_REQUEST,
    ):
        return True

    if not _seller_provided_bank_details(seller_message, conversation_context):
        return True

    asks_for_details = any(phrase in reply_result.text for phrase in _IBAN_REQUEST_PHRASES)
    if asks_for_details:
        issues.append("requests_information_already_provided")
        return False
    return True


def _check_concise(reply_result: ReplyGenerationResult, issues: list[str]) -> bool:
    if len(reply_result.text) > _MAX_REPLY_LENGTH:
        issues.append("reply_not_concise")
        return False
    return True


def _check_no_onboarding(reply_result: ReplyGenerationResult, issues: list[str]) -> bool:
    ok = True
    for phrase in FORBIDDEN_ONBOARDING_PHRASES:
        if phrase in reply_result.text:
            issues.append(f"onboarding_guidance:{phrase}")
            ok = False
    return ok


def _check_no_contradiction(
    seller_message: str,
    intent_result: IntentClassificationResult,
    reply_result: ReplyGenerationResult,
    conversation_context: list[ConversationMessage] | None,
    issues: list[str],
) -> bool:
    text = reply_result.text
    ok = True

    if intent_result.primary_intent == IntentId.COMPLAINT_ORDER_FOLLOWUP:
        if "؟" in text or any(phrase in text for phrase in _UNRELATED_QUESTION_PHRASES):
            issues.append("unrelated_question_in_complaint_followup")
            ok = False

    if intent_result.primary_intent == IntentId.SHOP_ADDRESS_UPDATE:
        for phrase in FORBIDDEN_ONBOARDING_PHRASES:
            if phrase in text:
                issues.append("address_reply_contains_onboarding")
                ok = False

    if _seller_provided_bank_details(seller_message, conversation_context):
        if any(phrase in text for phrase in _IBAN_REQUEST_PHRASES):
            issues.append("contradicts_seller_bank_submission")
            ok = False

    return ok


def evaluate_reply(
    seller_message: str,
    intent_result: IntentClassificationResult,
    reply_result: ReplyGenerationResult,
    conversation_context: list[ConversationMessage] | None = None,
) -> ReplyEvaluationResult:
    issues: list[str] = []

    checks = [
        _check_intent_match(intent_result, reply_result, issues),
        _check_no_redundant_request(
            seller_message,
            intent_result,
            reply_result,
            conversation_context,
            issues,
        ),
        _check_concise(reply_result, issues),
        _check_no_onboarding(reply_result, issues),
        _check_no_contradiction(
            seller_message,
            intent_result,
            reply_result,
            conversation_context,
            issues,
        ),
    ]

    score = sum(1 for ok in checks if ok) / len(checks)
    return ReplyEvaluationResult(
        passed=len(issues) == 0,
        score=score,
        issues=issues,
    )
