"""Full pipeline evaluation cases for real and near-real seller tickets."""

from dataclasses import dataclass, field

from app.intent.taxonomy import IntentId
from app.models.messages import ConversationMessage
from app.reply.templates import COMPLAINT_FOLLOWUP_REPLY

KNOWN_CASE_COUNT = 8
VARIATION_CASE_COUNT = 8


@dataclass(frozen=True)
class PipelineEvalCase:
    case_id: str
    message: str
    expected_intent: IntentId
    is_known: bool = True
    context: list[ConversationMessage] = field(default_factory=list)
    accepted_intents: tuple[IntentId, ...] = ()
    required_context_flags: tuple[str, ...] = ()
    required_negative_intents: tuple[IntentId, ...] = ()
    forbidden_predicted_intents: tuple[IntentId, ...] = ()
    reply_contains_any: tuple[str, ...] = ()
    reply_must_not_contain: tuple[str, ...] = ()
    reply_exact: str | None = None
    reply_must_not_ask_iban: bool = False


PIPELINE_EVAL_CASES: list[PipelineEvalCase] = [
    PipelineEvalCase(
        case_id="case_1_order_registration",
        message=(
            "سلام. مدتیست که سفارش ثبت نمیشود. لطفا بررسی فرمایید "
            "که آیا مشکلی پیش آمده یا نه."
        ),
        expected_intent=IntentId.ORDER_REGISTRATION_ISSUE,
        reply_contains_any=("ثبت سفارش", "عدم ثبت سفارش", "بررسی"),
    ),
    PipelineEvalCase(
        case_id="case_2_product_approval",
        message="وقت بخیر لطفا محصولاتی که هنوز تایید نشده رو تایید می کنید",
        expected_intent=IntentId.PRODUCT_APPROVAL_REQUEST,
        reply_contains_any=("محصول", "تأیید", "تایید", "بررسی"),
    ),
    PipelineEvalCase(
        case_id="case_3_shop_address",
        message=(
            "سلام . آدرس فروشگاه به آدرس اصفهان- اصفهان - خیابان احمداباد "
            "کوچه 5 شهید یزدخواستی مجتمع پارسیان ط4 واحد 10 تغییر یابد"
        ),
        expected_intent=IntentId.SHOP_ADDRESS_UPDATE,
        reply_contains_any=("تغییر آدرس", "آدرس"),
    ),
    PipelineEvalCase(
        case_id="case_4_bank_account_change",
        message=(
            "سلام وقت بخیر میخوام شماره حسابم رو لطفا تغییر بدین "
            "حساب فعلی من صادرات که میخوام سامان تغییر بدم"
        ),
        expected_intent=IntentId.BANK_ACCOUNT_CHANGE,
        reply_contains_any=("حساب", "شبا", "بررسی"),
    ),
    PipelineEvalCase(
        case_id="case_5_contract_after_iban",
        message=(
            "سلام شماره شبا رو فرستادم لطفا قرار داد همکاری رو تایید "
            "تا من بتونم محصولاتم رو ثبت کنم شمار شبا:510170000000216612060003"
        ),
        expected_intent=IntentId.CONTRACT_APPROVAL,
        reply_contains_any=("قرارداد", "بررسی"),
        reply_must_not_ask_iban=True,
    ),
    PipelineEvalCase(
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
        reply_contains_any=("قرارداد", "بررسی"),
        reply_must_not_ask_iban=True,
    ),
    PipelineEvalCase(
        case_id="case_7_settlement_bank_change",
        message=(
            "سلام به دلیل اختلال در بانک ملی برای تسویه حساب می خوام کارت جدید "
            "معرفی کنم. بانک خاورمیانه(بانکینو) شماره کارت: 5859471022669687 "
            "شماره شبا: 790780202010020000219015"
        ),
        expected_intent=IntentId.BANK_ACCOUNT_CHANGE,
        required_context_flags=("settlement_context",),
        required_negative_intents=(IntentId.SETTLEMENT_INQUIRY,),
        reply_contains_any=("حساب", "شبا", "بررسی"),
        reply_must_not_ask_iban=True,
    ),
    PipelineEvalCase(
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
        reply_exact=COMPLAINT_FOLLOWUP_REPLY,
    ),
    PipelineEvalCase(
        case_id="case_9_variation_order_registration",
        message=(
            "سلام چند روزه هیچ سفارشی برای فروشگاهم ثبت نشده، "
            "میشه بررسی کنید مشکل از پنله یا نه؟"
        ),
        expected_intent=IntentId.ORDER_REGISTRATION_ISSUE,
        is_known=False,
        reply_contains_any=("ثبت سفارش", "عدم ثبت سفارش", "بررسی"),
    ),
    PipelineEvalCase(
        case_id="case_10_variation_product_approval",
        message="سلام محصولات فروشگاهم در انتظار بررسی مونده لطفا رسیدگی کنید",
        expected_intent=IntentId.PRODUCT_APPROVAL_REQUEST,
        is_known=False,
        reply_contains_any=("بررسی", "تأیید", "تایید", "محصول"),
    ),
    PipelineEvalCase(
        case_id="case_11_variation_shop_address",
        message="سلام لطفا آدرس انبار رو به تهران، خیابان آزادی، پلاک ۲۳ تغییر بدید",
        expected_intent=IntentId.SHOP_ADDRESS_UPDATE,
        is_known=False,
        reply_contains_any=("تغییر آدرس", "آدرس"),
    ),
    PipelineEvalCase(
        case_id="case_12_variation_bank_with_iban",
        message=(
            "سلام میخوام شبا و شماره کارت فروشگاه رو تغییر بدم. "
            "شبا جدید: ۱۲۳۴۵۶۷۸۹"
        ),
        expected_intent=IntentId.BANK_ACCOUNT_CHANGE,
        is_known=False,
        reply_contains_any=("حساب", "شبا", "بررسی"),
        reply_must_not_ask_iban=True,
    ),
    PipelineEvalCase(
        case_id="case_13_variation_card_change_not_settlement",
        message=(
            "سلام برای واریزی‌های بعدی میخوام حسابم رو عوض کنم، "
            "شماره کارت جدید رو ارسال کردم"
        ),
        expected_intent=IntentId.BANK_ACCOUNT_CHANGE,
        accepted_intents=(IntentId.BANK_ACCOUNT_CHANGE, IntentId.CARD_CHANGE_REQUEST),
        is_known=False,
        forbidden_predicted_intents=(IntentId.SETTLEMENT_INQUIRY,),
        reply_contains_any=("حساب", "کارت", "بررسی"),
    ),
    PipelineEvalCase(
        case_id="case_14_variation_contract_followup",
        message="پس قرارداد کی تایید میشه؟",
        context=[
            ConversationMessage(
                role="user",
                content="سلام شماره شبا رو ارسال کردم برای تایید قرارداد",
            ),
        ],
        expected_intent=IntentId.CONTRACT_APPROVAL,
        is_known=False,
        reply_contains_any=("قرارداد", "بررسی"),
        reply_must_not_ask_iban=True,
    ),
    PipelineEvalCase(
        case_id="case_15_variation_complaint_followup",
        message=(
            "سلام با مشتری هماهنگ شد کالا رو مرجوع میکنن و مبلغ برگشت داده میشه"
        ),
        context=[
            ConversationMessage(
                role="assistant",
                content=(
                    "فروشنده گرامی در مورد سفارش INC-7350001 شکایتی از فروشگاه شما "
                    "ثبت شده است. متن شکایت خریدار: کالا آسیب دیده است."
                ),
            ),
        ],
        expected_intent=IntentId.COMPLAINT_ORDER_FOLLOWUP,
        is_known=False,
        reply_exact=COMPLAINT_FOLLOWUP_REPLY,
    ),
    PipelineEvalCase(
        case_id="case_16_variation_settlement_inquiry",
        message="سلام تسویه این هفته چه زمانی واریز میشه؟",
        expected_intent=IntentId.SETTLEMENT_INQUIRY,
        is_known=False,
        reply_contains_any=("تسویه",),
    ),
]
