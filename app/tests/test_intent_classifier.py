from app.intent.classifier import classify_intent
from app.intent.taxonomy import IntentId
from app.models.intent import SuggestedAction


def test_bank_change_with_settlement_not_settlement_inquiry() -> None:
    result = classify_intent("برای تسویه حساب باید شبا رو عوض کنم")

    assert result.primary_intent == IntentId.BANK_ACCOUNT_CHANGE
    assert result.primary_intent != IntentId.SETTLEMENT_INQUIRY
    assert "settlement_context" in result.context_flags
    assert IntentId.SETTLEMENT_INQUIRY in result.negative_intents
    assert result.suggested_action == SuggestedAction.REQUEST_MISSING_INFORMATION


def test_pure_settlement_timing_is_settlement_inquiry() -> None:
    result = classify_intent("تسویه این هفته کی واریز میشه؟")

    assert result.primary_intent == IntentId.SETTLEMENT_INQUIRY
    assert "settlement_context" in result.context_flags
    assert IntentId.SETTLEMENT_INQUIRY not in result.negative_intents


def test_product_approval_request() -> None:
    result = classify_intent("لطفا محصول جدیدم رو تایید کنید، هنوز تایید نشده")

    assert result.primary_intent == IntentId.PRODUCT_APPROVAL_REQUEST
    assert result.confidence >= 0.8
    assert result.evidence
    assert result.suggested_action == SuggestedAction.HUMAN_FOLLOWUP


def test_shop_address_update() -> None:
    result = classify_intent("میخوام آدرس فروشگاه رو عوض کنم، راهنمایی کنید")

    assert result.primary_intent == IntentId.SHOP_ADDRESS_UPDATE
    assert "آدرس" in result.evidence


def test_order_registration_issue() -> None:
    result = classify_intent("وقتی سفارش رو ثبت میکنم خطا میده و ثبت نمیشه")

    assert result.primary_intent == IntentId.ORDER_REGISTRATION_ISSUE
    assert result.suggested_action == SuggestedAction.ESCALATE


def test_contract_approval_after_iban_submission() -> None:
    result = classify_intent("شبا رو ثبت کردم، قرارداد کی تایید میشه؟")

    assert result.primary_intent == IntentId.CONTRACT_APPROVAL
    assert result.suggested_action == SuggestedAction.HUMAN_FOLLOWUP
