"""Real seller ticket cases for intent evaluation."""

from dataclasses import dataclass, field

from app.intent.taxonomy import IntentId
from app.models.messages import ConversationMessage


@dataclass(frozen=True)
class RealTicketCase:
    case_id: str
    message: str
    expected_intent: IntentId
    context: list[ConversationMessage] = field(default_factory=list)
    accepted_intents: tuple[IntentId, ...] = ()
    required_context_flags: tuple[str, ...] = ()
    required_negative_intents: tuple[IntentId, ...] = ()
    taxonomy_gap_note: str | None = None


REAL_TICKET_CASES: list[RealTicketCase] = [
    RealTicketCase(
        case_id="case_1_order_registration",
        message=(
            "سلام. مدتیست که سفارش ثبت نمیشود. لطفا بررسی فرمایید "
            "که آیا مشکلی پیش آمده یا نه."
        ),
        expected_intent=IntentId.ORDER_REGISTRATION_ISSUE,
    ),
    RealTicketCase(
        case_id="case_2_product_approval",
        message="وقت بخیر لطفا محصولاتی که هنوز تایید نشده رو تایید می کنید",
        expected_intent=IntentId.PRODUCT_APPROVAL_REQUEST,
    ),
    RealTicketCase(
        case_id="case_3_shop_address",
        message=(
            "سلام . آدرس فروشگاه به آدرس اصفهان- اصفهان - خیابان احمداباد "
            "کوچه 5 شهید یزدخواستی مجتمع پارسیان ط4 واحد 10 تغییر یابد"
        ),
        expected_intent=IntentId.SHOP_ADDRESS_UPDATE,
    ),
    RealTicketCase(
        case_id="case_4_bank_account_change",
        message=(
            "سلام وقت بخیر میخوام شماره حسابم رو لطفا تغییر بدین "
            "حساب فعلی من صادرات که میخوام سامان تغییر بدم"
        ),
        expected_intent=IntentId.BANK_ACCOUNT_CHANGE,
    ),
    RealTicketCase(
        case_id="case_5_contract_after_iban",
        message=(
            "سلام شماره شبا رو فرستادم لطفا قرار داد همکاری رو تایید "
            "تا من بتونم محصولاتم رو ثبت کنم شمار شبا:510170000000216612060003"
        ),
        expected_intent=IntentId.CONTRACT_APPROVAL,
    ),
    RealTicketCase(
        case_id="case_6_contract_followup_with_context",
        message="تایید شد شماره شبام",
        context=[
            ConversationMessage(
                role="user",
                content=(
                    "سلام شماره شبا رو فرستادم لطفا قرار داد همکاری رو تایید "
                    "تا من بتونم محصولاتم رو ثبت کنم "
                    "شمار شبا:510170000000216612060003"
                ),
            ),
        ],
        expected_intent=IntentId.CONTRACT_APPROVAL,
    ),
    RealTicketCase(
        case_id="case_7_settlement_bank_change",
        message=(
            "سلام به دلیل اختلال در بانک ملی برای تسویه حساب می خوام کارت جدید "
            "معرفی کنم. بانک خاورمیانه(بانکینو) شماره کارت: 5859471022669687 "
            "شماره شبا: 790780202010020000219015"
        ),
        expected_intent=IntentId.BANK_ACCOUNT_CHANGE,
        required_context_flags=("settlement_context",),
        required_negative_intents=(IntentId.SETTLEMENT_INQUIRY,),
    ),
    RealTicketCase(
        case_id="case_8_complaint_return_followup",
        message=(
            "سلام‌وقت‌به خیر تماس گرفته شد ، قرار شد محصول رو برگشت بدن‌"
            "و هزینه به حسابشون برگشت داده بشه"
        ),
        context=[
            ConversationMessage(
                role="assistant",
                content=(
                    'فروشنده گرامی در مورد سفارش INC-7342409 شکایتی از فروشگاه شما '
                    'ثبت شده است. متن شکایت خریدار : "سلام نیم ساعته کالا دستم '
                    'رسیده بازش کردم دارای شکستگی هست"'
                ),
            ),
        ],
        expected_intent=IntentId.COMPLAINT_ORDER_FOLLOWUP,
    ),
]
