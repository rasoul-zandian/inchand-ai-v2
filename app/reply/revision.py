from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult
from app.models.reply import (
    ReplyEvaluationResult,
    ReplyGenerationResult,
    ReplyRevisionResult,
)
from app.reply.templates import (
    BANK_CHANGE_REGISTERED_REPLY,
    COMPLAINT_FOLLOWUP_REPLY,
    FORBIDDEN_ONBOARDING_PHRASES,
    render_template,
)

_MAX_REPLY_LENGTH = 350
_TEMPLATE_REPLACEMENT_ISSUES = {
    "intent_mismatch",
    "shop_address_not_mentioned",
    "product_approval_not_mentioned",
    "settlement_not_mentioned",
    "complaint_reply_asks_question",
    "complaint_reply_unrelated_request",
    "complaint_reply_not_neutral_ack",
    "contradicts_seller",
}


def _has_issue(issues: list[str], prefix: str) -> bool:
    return any(issue == prefix or issue.startswith(f"{prefix}:") for issue in issues)


def _apply_onboarding_removal(text: str, intent_result: IntentClassificationResult) -> tuple[str, str | None]:
    if not any(phrase in text for phrase in FORBIDDEN_ONBOARDING_PHRASES):
        return text, None

    cleaned = text
    for phrase in FORBIDDEN_ONBOARDING_PHRASES:
        cleaned = cleaned.replace(phrase, "")
    cleaned = " ".join(cleaned.split())
    if cleaned and not any(phrase in cleaned for phrase in FORBIDDEN_ONBOARDING_PHRASES):
        return cleaned, "removed_onboarding_phrase"

    return render_template(intent_result), "removed_onboarding_phrase"


def revise_reply(
    seller_message: str,
    intent_result: IntentClassificationResult,
    reply_result: ReplyGenerationResult,
    evaluation_result: ReplyEvaluationResult,
) -> ReplyRevisionResult:
    del seller_message

    original_text = reply_result.text
    if evaluation_result.passed:
        return ReplyRevisionResult(
            revised=False,
            original_text=original_text,
            revised_text=original_text,
            revision_reason="",
        )

    issues = evaluation_result.issues
    revised_text = original_text
    reasons: list[str] = []

    if _has_issue(issues, "forbidden_onboarding"):
        revised_text, reason = _apply_onboarding_removal(revised_text, intent_result)
        if reason:
            reasons.append(reason)

    if "requests_iban_already_provided" in issues:
        if intent_result.primary_intent == IntentId.BANK_ACCOUNT_CHANGE:
            revised_text = BANK_CHANGE_REGISTERED_REPLY
            reasons.append("removed_redundant_iban_request")

    if any(issue in _TEMPLATE_REPLACEMENT_ISSUES for issue in issues):
        replacement = render_template(intent_result)
        if intent_result.primary_intent == IntentId.COMPLAINT_ORDER_FOLLOWUP:
            replacement = COMPLAINT_FOLLOWUP_REPLY
        revised_text = replacement
        reasons.append("replaced_unrelated_clarification")

    if "too_verbose" in issues:
        shortened = render_template(intent_result)
        if len(shortened) < len(revised_text):
            revised_text = shortened
            reasons.append("shortened_verbose_reply")

    unique_reasons: list[str] = []
    for reason in reasons:
        if reason not in unique_reasons:
            unique_reasons.append(reason)

    if len(revised_text) > _MAX_REPLY_LENGTH and "shortened_verbose_reply" not in unique_reasons:
        revised_text = render_template(intent_result)
        unique_reasons.append("shortened_verbose_reply")

    revised_text = revised_text.strip() or render_template(intent_result)
    revised = revised_text != original_text

    return ReplyRevisionResult(
        revised=revised,
        original_text=original_text,
        revised_text=revised_text,
        revision_reason="; ".join(unique_reasons),
    )
