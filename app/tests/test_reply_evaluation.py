import pytest

from app.intent.classifier import classify_intent
from app.intent.real_ticket_cases import REAL_TICKET_CASES
from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult, SuggestedAction
from app.models.reply import ReplyGenerationResult
from app.reply.evaluation import evaluate_reply
from app.reply.generator import generate_reply
from app.reply.templates import BANK_CHANGE_REQUEST_DETAILS_REPLY, SHOP_ADDRESS_REPLY


@pytest.mark.parametrize("case", REAL_TICKET_CASES, ids=lambda case: case.case_id)
def test_real_ticket_replies_pass_evaluation(case) -> None:
    context = case.context or None
    intent_result = classify_intent(case.message, conversation_context=context)
    reply = generate_reply(intent_result, conversation_context=context)
    evaluation = evaluate_reply(
        case.message,
        intent_result,
        reply,
        conversation_context=context,
    )

    assert evaluation.passed, evaluation.issues
    assert evaluation.score == 1.0


def test_bank_change_asking_for_iban_when_provided_fails() -> None:
    intent_result = IntentClassificationResult(
        primary_intent=IntentId.BANK_ACCOUNT_CHANGE,
        confidence=0.9,
        evidence=["شبا", "790780202010020000219015"],
        suggested_action=SuggestedAction.REQUEST_MISSING_INFORMATION,
    )
    reply = ReplyGenerationResult(
        text=BANK_CHANGE_REQUEST_DETAILS_REPLY,
        primary_intent=IntentId.BANK_ACCOUNT_CHANGE,
        suggested_action=SuggestedAction.REQUEST_MISSING_INFORMATION,
    )

    evaluation = evaluate_reply(
        "شماره شبا: 790780202010020000219015",
        intent_result,
        reply,
    )

    assert not evaluation.passed
    assert "requests_iban_already_provided" in evaluation.issues
    assert evaluation.score < 1.0


def test_onboarding_phrase_fails_for_non_onboarding_intent() -> None:
    intent_result = IntentClassificationResult(
        primary_intent=IntentId.SHOP_ADDRESS_UPDATE,
        confidence=0.9,
        evidence=["آدرس"],
        suggested_action=SuggestedAction.REQUEST_MISSING_INFORMATION,
    )
    reply = ReplyGenerationResult(
        text="لطفاً راه‌اندازی فروشگاه خود را تکمیل کنید.",
        primary_intent=IntentId.SHOP_ADDRESS_UPDATE,
        suggested_action=SuggestedAction.REQUEST_MISSING_INFORMATION,
    )

    evaluation = evaluate_reply("میخوام آدرس فروشگاه رو عوض کنم", intent_result, reply)

    assert not evaluation.passed
    assert any(issue.startswith("forbidden_onboarding:") for issue in evaluation.issues)


def test_general_inquiry_allows_clarification_request() -> None:
    intent_result = IntentClassificationResult(
        primary_intent=IntentId.GENERAL_INQUIRY,
        confidence=0.5,
        evidence=["fallback"],
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )
    reply = generate_reply(intent_result)
    evaluation = evaluate_reply("سلام", intent_result, reply)

    assert evaluation.passed


def test_shop_address_reply_passes_intent_specific_checks() -> None:
    intent_result = IntentClassificationResult(
        primary_intent=IntentId.SHOP_ADDRESS_UPDATE,
        confidence=0.9,
        evidence=["آدرس"],
        suggested_action=SuggestedAction.REQUEST_MISSING_INFORMATION,
    )
    reply = ReplyGenerationResult(
        text=SHOP_ADDRESS_REPLY,
        primary_intent=IntentId.SHOP_ADDRESS_UPDATE,
        suggested_action=SuggestedAction.REQUEST_MISSING_INFORMATION,
    )

    evaluation = evaluate_reply("میخوام آدرس فروشگاه رو عوض کنم", intent_result, reply)

    assert evaluation.passed
