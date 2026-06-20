import pytest

from app.intent.classifier import classify_intent
from app.intent.real_ticket_cases import REAL_TICKET_CASES
from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult, SuggestedAction
from app.models.reply import ReplyGenerationResult
from app.reply.evaluation import evaluate_reply
from app.reply.generator import generate_reply
from app.reply.templates import FORBIDDEN_ONBOARDING_PHRASES


@pytest.mark.parametrize("case", REAL_TICKET_CASES, ids=lambda case: case.case_id)
def test_real_ticket_replies_pass_evaluation(case) -> None:
    context = case.context or None
    intent_result = classify_intent(case.message, conversation_context=context)
    reply_result = generate_reply(intent_result, conversation_context=context)

    evaluation = evaluate_reply(
        case.message,
        intent_result,
        reply_result,
        conversation_context=context,
    )

    assert evaluation.passed, evaluation.issues
    assert evaluation.score == 1.0


def test_bank_change_with_provided_iban_must_not_request_iban_again() -> None:
    seller_message = (
        "شماره شبا: 790780202010020000219015 شماره کارت: 5859471022669687"
    )
    intent_result = IntentClassificationResult(
        primary_intent=IntentId.BANK_ACCOUNT_CHANGE,
        confidence=0.9,
        evidence=["شبا", "790780202010020000219015"],
        suggested_action=SuggestedAction.REQUEST_MISSING_INFORMATION,
    )
    reply_result = ReplyGenerationResult(
        text="درخواست تغییر اطلاعات حساب بانکی شما ثبت شد و در دست بررسی قرار گرفت.",
        primary_intent=IntentId.BANK_ACCOUNT_CHANGE,
        suggested_action=SuggestedAction.REQUEST_MISSING_INFORMATION,
    )

    evaluation = evaluate_reply(seller_message, intent_result, reply_result)

    assert evaluation.passed
    assert "requests_information_already_provided" not in evaluation.issues


def test_bank_change_bad_reply_requesting_iban_fails() -> None:
    seller_message = "شماره شبا: 790780202010020000219015"
    intent_result = IntentClassificationResult(
        primary_intent=IntentId.BANK_ACCOUNT_CHANGE,
        confidence=0.9,
        evidence=["شبا"],
        suggested_action=SuggestedAction.REQUEST_MISSING_INFORMATION,
    )
    reply_result = ReplyGenerationResult(
        text="لطفاً شماره شبا یا اطلاعات حساب بانکی جدید را ارسال کنید تا درخواست شما بررسی شود.",
        primary_intent=IntentId.BANK_ACCOUNT_CHANGE,
        suggested_action=SuggestedAction.REQUEST_MISSING_INFORMATION,
    )

    evaluation = evaluate_reply(seller_message, intent_result, reply_result)

    assert not evaluation.passed
    assert "requests_information_already_provided" in evaluation.issues


def test_complaint_followup_must_not_ask_unrelated_questions() -> None:
    intent_result = IntentClassificationResult(
        primary_intent=IntentId.COMPLAINT_ORDER_FOLLOWUP,
        confidence=0.9,
        evidence=["برگشت"],
        suggested_action=SuggestedAction.HUMAN_FOLLOWUP,
    )
    reply_result = ReplyGenerationResult(
        text="درخواست شما ثبت و در دست بررسی قرار گرفت.",
        primary_intent=IntentId.COMPLAINT_ORDER_FOLLOWUP,
        suggested_action=SuggestedAction.HUMAN_FOLLOWUP,
    )

    evaluation = evaluate_reply("تماس گرفته شد و کالا برگشت داده می‌شود", intent_result, reply_result)

    assert evaluation.passed


def test_complaint_followup_with_unrelated_question_fails() -> None:
    intent_result = IntentClassificationResult(
        primary_intent=IntentId.COMPLAINT_ORDER_FOLLOWUP,
        confidence=0.9,
        evidence=["برگشت"],
        suggested_action=SuggestedAction.HUMAN_FOLLOWUP,
    )
    reply_result = ReplyGenerationResult(
        text="لطفاً شماره شبا خود را ارسال کنید؟",
        primary_intent=IntentId.COMPLAINT_ORDER_FOLLOWUP,
        suggested_action=SuggestedAction.HUMAN_FOLLOWUP,
    )

    evaluation = evaluate_reply("تماس گرفته شد", intent_result, reply_result)

    assert not evaluation.passed
    assert "unrelated_question_in_complaint_followup" in evaluation.issues


def test_address_update_mentions_address_not_onboarding() -> None:
    intent_result = IntentClassificationResult(
        primary_intent=IntentId.SHOP_ADDRESS_UPDATE,
        confidence=0.9,
        evidence=["آدرس"],
        suggested_action=SuggestedAction.REQUEST_MISSING_INFORMATION,
    )
    reply_result = ReplyGenerationResult(
        text="درخواست تغییر آدرس فروشگاه شما ثبت شد و در دست بررسی قرار گرفت.",
        primary_intent=IntentId.SHOP_ADDRESS_UPDATE,
        suggested_action=SuggestedAction.REQUEST_MISSING_INFORMATION,
    )

    evaluation = evaluate_reply("میخوام آدرس فروشگاه رو عوض کنم", intent_result, reply_result)

    assert evaluation.passed
    for phrase in FORBIDDEN_ONBOARDING_PHRASES:
        assert phrase not in reply_result.text


def test_product_approval_mentions_product_review() -> None:
    intent_result = IntentClassificationResult(
        primary_intent=IntentId.PRODUCT_APPROVAL_REQUEST,
        confidence=0.9,
        evidence=["محصول", "تایید"],
        suggested_action=SuggestedAction.HUMAN_FOLLOWUP,
    )
    reply_result = generate_reply(intent_result)

    evaluation = evaluate_reply("لطفا محصولاتم رو تایید کنید", intent_result, reply_result)

    assert evaluation.passed
    assert "محصول" in reply_result.text
    assert "تأیید" in reply_result.text or "تایید" in reply_result.text or "بررسی" in reply_result.text
