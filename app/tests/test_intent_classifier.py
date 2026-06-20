import pytest

from app.intent.classifier import classify_intent
from app.intent.taxonomy import IntentId
from app.models.messages import ConversationMessage


@pytest.mark.parametrize(
    ("message", "expected_intent", "settlement_context"),
    [
        (
            "وقتی سفارش رو ثبت میکنم خطا میده و ثبت نمیشه",
            IntentId.ORDER_REGISTRATION_ISSUE,
            False,
        ),
        (
            "لطفا محصول جدیدم رو تایید کنید، هنوز تایید نشده",
            IntentId.PRODUCT_APPROVAL_REQUEST,
            False,
        ),
        (
            "میخوام آدرس فروشگاه رو عوض کنم، راهنمایی کنید",
            IntentId.SHOP_ADDRESS_UPDATE,
            False,
        ),
        (
            "میخوام شماره شبا و حساب بانکی رو تغییر بدم",
            IntentId.BANK_ACCOUNT_CHANGE,
            False,
        ),
        (
            "شبا رو ثبت کردم، قرارداد کی تایید میشه؟",
            IntentId.CONTRACT_APPROVAL,
            False,
        ),
        (
            "برای تسویه حساب باید شبا رو عوض کنم",
            IntentId.BANK_ACCOUNT_CHANGE,
            True,
        ),
    ],
    ids=[
        "order_registration_issue",
        "product_approval_request",
        "shop_address_update",
        "bank_account_change",
        "contract_approval_after_iban",
        "bank_account_change_settlement",
    ],
)
def test_classify_intent_failed_examples(
    message: str,
    expected_intent: IntentId,
    settlement_context: bool,
) -> None:
    context = (
        [ConversationMessage(role="user", content="موضوع تسویه حساب")]
        if settlement_context
        else None
    )
    result = classify_intent(message, conversation_context=context)

    assert result.intent == expected_intent
    assert result.confidence >= 0.0
    assert result.rationale
    assert result.settlement_context is settlement_context
