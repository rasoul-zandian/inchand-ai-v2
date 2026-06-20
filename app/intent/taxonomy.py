"""Intent taxonomy for merchant support classification."""

from enum import Enum

from pydantic import BaseModel


class IntentId(str, Enum):
    ORDER_REGISTRATION_ISSUE = "order_registration_issue"
    PRODUCT_APPROVAL_REQUEST = "product_approval_request"
    SHOP_ADDRESS_UPDATE = "shop_address_update"
    BANK_ACCOUNT_CHANGE = "bank_account_change"
    CONTRACT_APPROVAL = "contract_approval"


class IntentDefinition(BaseModel):
    id: IntentId
    label: str
    description: str
    examples: list[str]


INTENT_TAXONOMY: list[IntentDefinition] = [
    IntentDefinition(
        id=IntentId.ORDER_REGISTRATION_ISSUE,
        label="Order registration issue",
        description="Merchant cannot register or complete an order in the system.",
        examples=[
            "سفارش ثبت نمیشه و خطا میده",
            "وقتی سفارش رو ثبت میکنم ارور میگیرم",
        ],
    ),
    IntentDefinition(
        id=IntentId.PRODUCT_APPROVAL_REQUEST,
        label="Product approval request",
        description="Merchant asks for a product listing to be reviewed or approved.",
        examples=[
            "لطفا محصول جدیدم رو تایید کنید",
            "محصولم هنوز تایید نشده",
        ],
    ),
    IntentDefinition(
        id=IntentId.SHOP_ADDRESS_UPDATE,
        label="Shop address update",
        description="Merchant requests to change shop or warehouse address.",
        examples=[
            "میخوام آدرس فروشگاه رو عوض کنم",
            "آدرس انبار رو چطور آپدیت کنم",
        ],
    ),
    IntentDefinition(
        id=IntentId.BANK_ACCOUNT_CHANGE,
        label="Bank account change",
        description="Merchant requests to update IBAN or bank account details.",
        examples=[
            "میخوام شماره شبا رو تغییر بدم",
            "حساب بانکی جدید ثبت کنم",
        ],
    ),
    IntentDefinition(
        id=IntentId.CONTRACT_APPROVAL,
        label="Contract approval",
        description="Merchant follows up on contract approval after submitting IBAN.",
        examples=[
            "شبا رو ثبت کردم، قرارداد کی تایید میشه",
            "بعد از ثبت شبا قرارداد من تایید نشده",
        ],
    ),
]

INTENT_BY_ID = {item.id: item for item in INTENT_TAXONOMY}
