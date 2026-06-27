import re

from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult

ORDER_REGISTRATION_REPLY = (
    "درخواست شما ثبت شد و موضوع عدم ثبت سفارش در دست بررسی قرار گرفت."
)
PRODUCT_APPROVAL_REPLY = (
    "درخواست شما برای بررسی و تأیید محصولات ثبت شد و در دست بررسی قرار گرفت."
)
SHOP_ADDRESS_REPLY = (
    "درخواست تغییر آدرس فروشگاه شما ثبت شد و در دست بررسی قرار گرفت."
)
BANK_CHANGE_REGISTERED_REPLY = (
    "درخواست تغییر اطلاعات حساب بانکی شما ثبت شد و در دست بررسی قرار گرفت."
)
BANK_CHANGE_REQUEST_DETAILS_REPLY = (
    "لطفاً شماره شبا یا اطلاعات حساب بانکی جدید را ارسال کنید تا درخواست شما بررسی شود."
)
CARD_CHANGE_REPLY = (
    "درخواست ثبت یا تغییر شماره کارت شما ثبت شد و در دست بررسی قرار گرفت."
)
CONTRACT_APPROVAL_REPLY = (
    "درخواست شما برای بررسی وضعیت قرارداد همکاری ثبت شد و در دست بررسی قرار گرفت."
)
SETTLEMENT_INQUIRY_REPLY = (
    "درخواست شما درباره وضعیت تسویه ثبت شد و در دست بررسی قرار گرفت."
)
COMPLAINT_FOLLOWUP_REPLY = "درخواست شما ثبت و در دست بررسی قرار گرفت."
DELIVERY_CONFIRMATION_REPLY = (
    "اطلاع شما درباره تحویل سفارش ثبت شد و در دست بررسی قرار گرفت."
)
DELIVERY_CONFIRMATION_MISSING_ORDER_ID_REPLY = (
    "سلام، لطفاً جهت پیگیری، شماره سفارش را ارسال بفرمایید."
)
GENERAL_INQUIRY_REPLY = (
    "لطفاً موضوع درخواست خود را دقیق‌تر توضیح دهید تا بررسی شود."
)
DEFAULT_REGISTERED_REPLY = "درخواست شما ثبت شد و در دست بررسی قرار گرفت."

FORBIDDEN_ONBOARDING_PHRASES = (
    "راه‌اندازی فروشگاه",
    "تکمیل قرارداد فروشگاه",
    "اطلاعات ناقص فروشگاه",
)

_BANK_DETAIL_MARKERS = ("شبا", "iban", "کارت", "card")
_DIGIT_SEQUENCE = re.compile(r"\d{10,}")


def _entity_text_parts(intent_result: IntentClassificationResult) -> list[str]:
    parts: list[str] = []
    for value in intent_result.entities.values():
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        else:
            parts.append(str(value))
    return parts


def _has_bank_details_provided(intent_result: IntentClassificationResult) -> bool:
    parts = list(intent_result.evidence) + _entity_text_parts(intent_result)
    for part in parts:
        lowered = part.lower()
        if any(marker in lowered for marker in _BANK_DETAIL_MARKERS):
            return True
        if _DIGIT_SEQUENCE.search(part):
            return True
    return False


def render_template(intent_result: IntentClassificationResult) -> str:
    intent = intent_result.primary_intent

    if intent == IntentId.ORDER_REGISTRATION_ISSUE:
        return ORDER_REGISTRATION_REPLY
    if intent == IntentId.PRODUCT_APPROVAL_REQUEST:
        return PRODUCT_APPROVAL_REPLY
    if intent == IntentId.SHOP_ADDRESS_UPDATE:
        return SHOP_ADDRESS_REPLY
    if intent == IntentId.BANK_ACCOUNT_CHANGE:
        if _has_bank_details_provided(intent_result):
            return BANK_CHANGE_REGISTERED_REPLY
        return BANK_CHANGE_REQUEST_DETAILS_REPLY
    if intent == IntentId.CARD_CHANGE_REQUEST:
        return CARD_CHANGE_REPLY
    if intent == IntentId.CONTRACT_APPROVAL:
        return CONTRACT_APPROVAL_REPLY
    if intent == IntentId.SETTLEMENT_INQUIRY:
        return SETTLEMENT_INQUIRY_REPLY
    if intent == IntentId.COMPLAINT_ORDER_FOLLOWUP:
        return COMPLAINT_FOLLOWUP_REPLY
    if intent == IntentId.DELIVERY_CONFIRMATION_REQUEST:
        return DELIVERY_CONFIRMATION_REPLY
    if intent == IntentId.GENERAL_INQUIRY:
        return GENERAL_INQUIRY_REPLY

    return DEFAULT_REGISTERED_REPLY
