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


def test_delivery_confirmation_request_examples() -> None:
    result = classify_intent("سفارش تحویل مشتری شد")
    assert result.primary_intent == IntentId.DELIVERY_CONFIRMATION_REQUEST

    result = classify_intent("کالا به دست مشتری رسیده")
    assert result.primary_intent == IntentId.DELIVERY_CONFIRMATION_REQUEST


def test_complaint_context_delivery_followup_stays_complaint() -> None:
    context = [
        ConversationMessage(
            role="assistant",
            content=(
                "فروشنده گرامی در مورد سفارش INC-7342409 شکایتی از فروشگاه شما ثبت شده است."
            ),
        ),
    ]
    message = "سلام وقت بخیر بسته را تحویل و هزینه برگشت را پرداخت کردن"

    result = classify_intent(message, conversation_context=context)

    assert result.primary_intent == IntentId.COMPLAINT_ORDER_FOLLOWUP
    assert result.primary_intent != IntentId.DELIVERY_CONFIRMATION_REQUEST


def test_complaint_context_with_seller_address_status_message() -> None:
    context = [
        ConversationMessage(
            role="assistant",
            content=(
                "فروشنده گرامی متن شکایت خریدار: کالا معیوب بود. "
                "در مورد سفارش INC-7342409 لطفا پیگیری کنید."
            ),
        ),
    ]
    message = (
        "علیرضا حسین پور 09302751516 بوشهر - بندرگناوه "
        "خیابان رزمندگان ۸ پلاک ۳ کد پستی: 7531653715"
    )

    result = classify_intent(message, conversation_context=context)

    assert result.primary_intent == IntentId.COMPLAINT_ORDER_FOLLOWUP
    assert "complaint_context" in result.context_flags


def test_bank_account_change_not_overridden_by_complaint_context() -> None:
    context = [
        ConversationMessage(
            role="assistant",
            content="در مورد سفارش INC-7342409 شکایتی ثبت شده است.",
        ),
    ]
    message = (
        "سلام به دلیل اختلال در بانک ملی برای تسویه حساب می خوام کارت جدید "
        "معرفی کنم. شماره شبا: 790780202010020000219015"
    )

    result = classify_intent(message, conversation_context=context)

    assert result.primary_intent == IntentId.BANK_ACCOUNT_CHANGE
    assert result.primary_intent != IntentId.COMPLAINT_ORDER_FOLLOWUP


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


def test_complaint_room_cancel_request_is_complaint_followup() -> None:
    result = classify_intent("لطفا سفارششتون رو لغو کنید", room_type="complaint")

    assert result.primary_intent == IntentId.COMPLAINT_ORDER_FOLLOWUP
    assert result.primary_intent != IntentId.ORDER_CANCELLATION


def test_complaint_room_return_update_is_complaint_followup() -> None:
    result = classify_intent("کالا برگشت داده شد", room_type="complaint")

    assert result.primary_intent == IntentId.COMPLAINT_ORDER_FOLLOWUP


def test_complaint_room_delivery_confirmation_stays_delivery() -> None:
    result = classify_intent("سفارش تحویل مشتری شد", room_type="complaint")

    assert result.primary_intent == IntentId.DELIVERY_CONFIRMATION_REQUEST
    assert result.primary_intent != IntentId.COMPLAINT_ORDER_FOLLOWUP


def test_fund_room_settlement_wording() -> None:
    result = classify_intent("تسویه این هفته کی واریز میشه؟", room_type="fund")

    assert result.primary_intent == IntentId.SETTLEMENT_INQUIRY
    assert "room_type_fund" in result.context_flags


def test_fund_room_iban_is_bank_account_change() -> None:
    result = classify_intent(
        "میخوام شماره شبا رو تغییر بدم IR800560213788805260753001",
        room_type="fund",
    )

    assert result.primary_intent == IntentId.BANK_ACCOUNT_CHANGE


def test_fund_room_card_is_card_change_request() -> None:
    result = classify_intent("شماره کارت جدید: 6219861091629898", room_type="fund")

    assert result.primary_intent == IntentId.CARD_CHANGE_REQUEST


def test_support_room_product_approval_unchanged() -> None:
    result = classify_intent(
        "لطفا محصولاتی که هنوز تایید نشده رو تایید می کنید",
        room_type="support",
    )

    assert result.primary_intent == IntentId.PRODUCT_APPROVAL_REQUEST


def test_thread_aware_shipping_resend_followup() -> None:
    context = [
        ConversationMessage(
            role="assistant",
            content="سفارش INC-7342409 برگشت خورده دوباره ارسال بشه",
        ),
    ]
    result = classify_intent_with_rules("چشم", conversation_context=context)

    assert result.primary_intent == IntentId.SHIPPING_INQUIRY
    assert "context_used" in result.evidence


def test_thread_aware_shop_activation_followup() -> None:
    context = [
        ConversationMessage(
            role="assistant",
            content="فروشگاه منو فعال کنید",
        ),
    ]
    result = classify_intent_with_rules("بله", conversation_context=context)

    assert result.primary_intent == IntentId.SHOP_PROFILE_UPDATE
    assert "context_used" in result.evidence


def test_thread_aware_product_spec_continuation() -> None:
    context = [
        ConversationMessage(
            role="assistant",
            content="مشخصات فنی را اضافه بفرمایید",
        ),
    ]
    result = classify_intent_with_rules(
        "ابعاد ۱۰ در ۲۰ سانتی‌متر",
        conversation_context=context,
    )

    assert result.primary_intent == IntentId.PRODUCT_EDIT_REQUEST
    assert "context_used" in result.evidence


def test_thread_aware_delivery_confirmation_with_order_ids() -> None:
    context = [
        ConversationMessage(
            role="assistant",
            content="لطفا تایید کنید سفارش‌های زیر تحویل مشتری شده‌اند",
        ),
    ]
    result = classify_intent_with_rules(
        "7347247 - 7345180 - 7344196",
        conversation_context=context,
    )

    assert result.primary_intent == IntentId.DELIVERY_CONFIRMATION_REQUEST
    assert "context_used" in result.evidence


def test_thread_aware_complaint_room_stays_complaint() -> None:
    context = [
        ConversationMessage(
            role="assistant",
            content="در مورد سفارش INC-7342409 شکایتی ثبت شده است",
        ),
    ]
    result = classify_intent_with_rules(
        "بله",
        conversation_context=context,
        room_type="complaint",
    )

    assert result.primary_intent == IntentId.COMPLAINT_ORDER_FOLLOWUP


def test_thread_aware_no_context_vague_stays_general() -> None:
    result = classify_intent_with_rules("چشم")

    assert result.primary_intent == IntentId.GENERAL_INQUIRY
    assert "context_used" not in result.evidence


def test_thread_aware_bank_in_current_not_overridden_by_context() -> None:
    context = [
        ConversationMessage(
            role="assistant",
            content="سفارش INC-7342409 برگشت خورده دوباره ارسال بشه",
        ),
    ]
    message = "شماره شبا: IR800560213788805260753001"
    result = classify_intent_with_rules(message, conversation_context=context)

    assert result.primary_intent == IntentId.BANK_ACCOUNT_CHANGE
    assert "context_used" not in result.evidence
