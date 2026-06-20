from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult, SuggestedAction
from app.models.reply import ReplyGenerationResult
from app.reply.evaluation import evaluate_reply
from app.reply.revision import revise_reply
from app.reply.templates import (
    BANK_CHANGE_REGISTERED_REPLY,
    BANK_CHANGE_REQUEST_DETAILS_REPLY,
    SHOP_ADDRESS_REPLY,
)


def test_iban_already_provided_revision_removes_iban_request() -> None:
    seller_message = "شماره شبا: 790780202010020000219015"
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
    evaluation = evaluate_reply(seller_message, intent_result, reply)

    assert not evaluation.passed

    revision = revise_reply(seller_message, intent_result, reply, evaluation)

    assert revision.revised
    assert revision.revised_text == BANK_CHANGE_REGISTERED_REPLY
    assert "لطفاً شماره شبا" not in revision.revised_text
    assert "removed_redundant_iban_request" in revision.revision_reason


def test_onboarding_phrase_revision_removes_onboarding_text() -> None:
    seller_message = "میخوام آدرس فروشگاه رو عوض کنم"
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
    evaluation = evaluate_reply(seller_message, intent_result, reply)

    assert not evaluation.passed

    revision = revise_reply(seller_message, intent_result, reply, evaluation)

    assert revision.revised
    assert "راه‌اندازی فروشگاه" not in revision.revised_text
    assert revision.revised_text == SHOP_ADDRESS_REPLY
    assert "removed_onboarding_phrase" in revision.revision_reason


def test_passed_reply_unchanged() -> None:
    seller_message = "میخوام آدرس فروشگاه رو عوض کنم"
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
    evaluation = evaluate_reply(seller_message, intent_result, reply)

    assert evaluation.passed

    revision = revise_reply(seller_message, intent_result, reply, evaluation)

    assert not revision.revised
    assert revision.original_text == SHOP_ADDRESS_REPLY
    assert revision.revised_text == SHOP_ADDRESS_REPLY
    assert revision.revision_reason == ""
