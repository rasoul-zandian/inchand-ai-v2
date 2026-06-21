import pytest

from app.intent.classifier import classify_intent
from app.intent.real_ticket_cases import REAL_TICKET_CASES
from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult, SuggestedAction
from app.reply.generator import generate_reply
from app.reply.templates import (
    BANK_CHANGE_REGISTERED_REPLY,
    BANK_CHANGE_REQUEST_DETAILS_REPLY,
    COMPLAINT_FOLLOWUP_REPLY,
    CONTRACT_APPROVAL_REPLY,
    DELIVERY_CONFIRMATION_REPLY,
    FORBIDDEN_ONBOARDING_PHRASES,
    ORDER_REGISTRATION_REPLY,
    PRODUCT_APPROVAL_REPLY,
    SETTLEMENT_INQUIRY_REPLY,
    SHOP_ADDRESS_REPLY,
)


REAL_TICKET_EXPECTED_REPLIES = {
    "case_1_order_registration": ORDER_REGISTRATION_REPLY,
    "case_2_product_approval": PRODUCT_APPROVAL_REPLY,
    "case_3_shop_address": SHOP_ADDRESS_REPLY,
    "case_4_bank_account_change": BANK_CHANGE_REQUEST_DETAILS_REPLY,
    "case_5_contract_after_iban": CONTRACT_APPROVAL_REPLY,
    "case_6_contract_followup_with_context": CONTRACT_APPROVAL_REPLY,
    "case_7_settlement_bank_change": BANK_CHANGE_REGISTERED_REPLY,
    "case_8_complaint_return_followup": COMPLAINT_FOLLOWUP_REPLY,
}


@pytest.mark.parametrize("case", REAL_TICKET_CASES, ids=lambda case: case.case_id)
def test_real_ticket_cases_generate_expected_reply(case) -> None:
    context = case.context or None
    intent_result = classify_intent(case.message, conversation_context=context)
    reply = generate_reply(intent_result, conversation_context=context)

    assert reply.source == "template"
    assert reply.primary_intent == intent_result.primary_intent
    assert reply.text == REAL_TICKET_EXPECTED_REPLIES[case.case_id]


def test_bank_change_with_provided_iban_does_not_request_iban_again() -> None:
    intent_result = IntentClassificationResult(
        primary_intent=IntentId.BANK_ACCOUNT_CHANGE,
        confidence=0.9,
        evidence=["شبا", "790780202010020000219015"],
        suggested_action=SuggestedAction.REQUEST_MISSING_INFORMATION,
    )

    reply = generate_reply(intent_result)

    assert reply.text == BANK_CHANGE_REGISTERED_REPLY
    assert "لطفاً شماره شبا" not in reply.text


def test_delivery_confirmation_reply_template() -> None:
    intent_result = IntentClassificationResult(
        primary_intent=IntentId.DELIVERY_CONFIRMATION_REQUEST,
        confidence=0.9,
        evidence=["تحویل"],
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )

    reply = generate_reply(intent_result)

    assert reply.text == DELIVERY_CONFIRMATION_REPLY


def test_complaint_order_followup_reply_is_exact() -> None:
    intent_result = IntentClassificationResult(
        primary_intent=IntentId.COMPLAINT_ORDER_FOLLOWUP,
        confidence=0.9,
        evidence=["برگشت"],
        suggested_action=SuggestedAction.HUMAN_FOLLOWUP,
    )

    reply = generate_reply(intent_result)

    assert reply.text == "درخواست شما ثبت و در دست بررسی قرار گرفت."


def test_no_reply_contains_onboarding_phrases() -> None:
    sample_intents = [
        IntentClassificationResult(
            primary_intent=intent_id,
            confidence=0.8,
            evidence=["نمونه"],
            suggested_action=SuggestedAction.REPLY_TO_SELLER,
        )
        for intent_id in IntentId
    ]

    for intent_result in sample_intents:
        reply = generate_reply(intent_result)
        for phrase in FORBIDDEN_ONBOARDING_PHRASES:
            assert phrase not in reply.text


def test_settlement_inquiry_reply() -> None:
    intent_result = IntentClassificationResult(
        primary_intent=IntentId.SETTLEMENT_INQUIRY,
        confidence=0.9,
        evidence=["تسویه"],
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )

    reply = generate_reply(intent_result)

    assert reply.text == SETTLEMENT_INQUIRY_REPLY
