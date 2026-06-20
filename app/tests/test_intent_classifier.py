import json

from app.config import settings
from app.intent.classifier import classify_intent, classify_intent_with_rules
from app.intent.taxonomy import IntentId
from app.models.intent import SuggestedAction


from app.models.messages import ConversationMessage


def test_unknown_negative_intents_are_skipped_not_fatal(monkeypatch) -> None:
    monkeypatch.setattr(settings, "intent_classifier_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    llm_payload = {
        "primary_intent": "product_approval_request",
        "confidence": 0.9,
        "evidence": ["تایید"],
        "entities": {},
        "context_flags": [],
        "negative_intents": ["settlement_inquiry", "made_up_intent"],
        "suggested_action": "human_followup",
    }

    def fake_request(_api_key, _model, _temperature, _messages):
        return json.dumps(llm_payload)

    monkeypatch.setattr(
        "app.intent.llm_classifier._default_request_openai",
        fake_request,
    )

    result = classify_intent("لطفا محصول جدیدم رو تایید کنید")

    assert result.primary_intent == IntentId.PRODUCT_APPROVAL_REQUEST
    assert result.fallback_reason is None
    assert result.negative_intents == [IntentId.SETTLEMENT_INQUIRY]


def test_bank_and_card_with_settlement_prefers_bank_account_change() -> None:
    message = (
        "سلام به دلیل اختلال در بانک ملی برای تسویه حساب می خوام کارت جدید "
        "معرفی کنم. شماره کارت: 5859471022669687 شماره شبا: 790780202010020000219015"
    )
    result = classify_intent(message)

    assert result.primary_intent == IntentId.BANK_ACCOUNT_CHANGE
    assert "settlement_context" in result.context_flags
    assert "card_provided" in result.context_flags
    assert IntentId.SETTLEMENT_INQUIRY in result.negative_intents


def test_complaint_context_with_seller_followup() -> None:
    context = [
        ConversationMessage(
            role="assistant",
            content=(
                "فروشنده گرامی در مورد سفارش INC-7342409 شکایتی از فروشگاه شما ثبت شده است."
            ),
        ),
    ]
    message = (
        "تماس گرفته شد، قرار شد کالا برگشت داده شود و هزینه به حسابشون برگشت داده بشه"
    )

    result = classify_intent(message, conversation_context=context)

    assert result.primary_intent == IntentId.COMPLAINT_ORDER_FOLLOWUP
    assert result.primary_intent != IntentId.BANK_ACCOUNT_CHANGE
    assert result.primary_intent != IntentId.RETURN_REFUND_INQUIRY


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


def test_provider_rule_uses_rule_classifier(monkeypatch) -> None:
    monkeypatch.setattr(settings, "intent_classifier_provider", "rule")

    result = classify_intent("تسویه این هفته کی واریز میشه؟")

    assert result.primary_intent == IntentId.SETTLEMENT_INQUIRY
    assert result.fallback_reason is None


def test_provider_openai_returns_structured_classification(monkeypatch) -> None:
    monkeypatch.setattr(settings, "intent_classifier_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    llm_payload = {
        "primary_intent": "product_approval_request",
        "confidence": 0.92,
        "evidence": ["محصول جدید", "تایید کنید"],
        "entities": {},
        "context_flags": [],
        "negative_intents": [],
        "suggested_action": "human_followup",
    }

    def fake_request(_api_key, _model, _temperature, _messages):
        return json.dumps(llm_payload)

    monkeypatch.setattr(
        "app.intent.llm_classifier._default_request_openai",
        fake_request,
    )

    result = classify_intent("لطفا محصول جدیدم رو تایید کنید")

    assert result.primary_intent == IntentId.PRODUCT_APPROVAL_REQUEST
    assert result.confidence == 0.92
    assert result.evidence == ["محصول جدید", "تایید کنید"]
    assert result.suggested_action == SuggestedAction.HUMAN_FOLLOWUP
    assert result.fallback_reason is None


def test_invalid_llm_intent_falls_back_to_rule_classifier(monkeypatch) -> None:
    monkeypatch.setattr(settings, "intent_classifier_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    def fake_request(_api_key, _model, _temperature, _messages):
        return json.dumps({"primary_intent": "made_up_intent", "confidence": 0.9})

    monkeypatch.setattr(
        "app.intent.llm_classifier._default_request_openai",
        fake_request,
    )

    message = "وقتی سفارش رو ثبت میکنم خطا میده و ثبت نمیشه"
    expected = classify_intent_with_rules(message)

    result = classify_intent(message)

    assert result.primary_intent == expected.primary_intent
    assert result.fallback_reason == "unknown_intent"


def test_openai_settlement_bank_change_not_settlement_inquiry(monkeypatch) -> None:
    monkeypatch.setattr(settings, "intent_classifier_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    llm_payload = {
        "primary_intent": "bank_account_change",
        "confidence": 0.91,
        "evidence": ["تسویه", "شبا"],
        "entities": {},
        "context_flags": ["settlement_context"],
        "negative_intents": ["settlement_inquiry"],
        "suggested_action": "request_missing_information",
    }

    def fake_request(_api_key, _model, _temperature, _messages):
        return json.dumps(llm_payload)

    monkeypatch.setattr(
        "app.intent.llm_classifier._default_request_openai",
        fake_request,
    )

    result = classify_intent("برای تسویه حساب باید شبا رو عوض کنم")

    assert result.primary_intent == IntentId.BANK_ACCOUNT_CHANGE
    assert result.primary_intent != IntentId.SETTLEMENT_INQUIRY
    assert "settlement_context" in result.context_flags
    assert IntentId.SETTLEMENT_INQUIRY in result.negative_intents
    assert result.fallback_reason is None
