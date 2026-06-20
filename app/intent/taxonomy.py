"""Intent taxonomy for merchant support classification."""

from enum import Enum

from pydantic import BaseModel


class IntentId(str, Enum):
    ORDER_REGISTRATION_ISSUE = "order_registration_issue"
    ORDER_STATUS_INQUIRY = "order_status_inquiry"
    ORDER_CANCELLATION = "order_cancellation"
    PRODUCT_APPROVAL_REQUEST = "product_approval_request"
    PRODUCT_REJECTION_INQUIRY = "product_rejection_inquiry"
    PRODUCT_EDIT_REQUEST = "product_edit_request"
    SHOP_ADDRESS_UPDATE = "shop_address_update"
    SHOP_PROFILE_UPDATE = "shop_profile_update"
    BANK_ACCOUNT_CHANGE = "bank_account_change"
    CARD_CHANGE_REQUEST = "card_change_request"
    CONTRACT_APPROVAL = "contract_approval"
    SETTLEMENT_INQUIRY = "settlement_inquiry"
    DOCUMENT_SUBMISSION = "document_submission"
    ACCOUNT_ACCESS_ISSUE = "account_access_issue"
    COMMISSION_INQUIRY = "commission_inquiry"
    SHIPPING_INQUIRY = "shipping_inquiry"
    RETURN_REFUND_INQUIRY = "return_refund_inquiry"
    COMPLAINT_ORDER_FOLLOWUP = "complaint_order_followup"
    TECHNICAL_BUG_REPORT = "technical_bug_report"
    GENERAL_INQUIRY = "general_inquiry"


class IntentDefinition(BaseModel):
    id: IntentId
    label: str
    description: str
    examples: list[str]


INTENT_TAXONOMY: list[IntentDefinition] = [
    IntentDefinition(
        id=IntentId.ORDER_REGISTRATION_ISSUE,
        label="Order registration issue",
        description="Merchant cannot register or complete an order.",
        examples=["سفارش ثبت نمیشه و خطا میده"],
    ),
    IntentDefinition(
        id=IntentId.ORDER_STATUS_INQUIRY,
        label="Order status inquiry",
        description="Merchant asks about order progress or delivery status.",
        examples=["سفارش ۱۲۳۴۵ الان کجاست؟"],
    ),
    IntentDefinition(
        id=IntentId.ORDER_CANCELLATION,
        label="Order cancellation",
        description="Merchant wants to cancel an order.",
        examples=["میخوام سفارش رو لغو کنم"],
    ),
    IntentDefinition(
        id=IntentId.PRODUCT_APPROVAL_REQUEST,
        label="Product approval request",
        description="Merchant asks for product listing review or approval.",
        examples=["لطفا محصول جدیدم رو تایید کنید"],
    ),
    IntentDefinition(
        id=IntentId.PRODUCT_REJECTION_INQUIRY,
        label="Product rejection inquiry",
        description="Merchant asks why a product was rejected.",
        examples=["محصولم چرا رد شد؟"],
    ),
    IntentDefinition(
        id=IntentId.PRODUCT_EDIT_REQUEST,
        label="Product edit request",
        description="Merchant wants to change product details.",
        examples=["قیمت محصول رو عوض کنم"],
    ),
    IntentDefinition(
        id=IntentId.SHOP_ADDRESS_UPDATE,
        label="Shop address update",
        description="Merchant requests shop or warehouse address change.",
        examples=["میخوام آدرس فروشگاه رو عوض کنم"],
    ),
    IntentDefinition(
        id=IntentId.SHOP_PROFILE_UPDATE,
        label="Shop profile update",
        description="Merchant wants to change non-address shop info.",
        examples=["نام فروشگاه رو تغییر بدم"],
    ),
    IntentDefinition(
        id=IntentId.BANK_ACCOUNT_CHANGE,
        label="Bank account change",
        description="Merchant requests IBAN or bank account update.",
        examples=["میخوام شماره شبا رو تغییر بدم"],
    ),
    IntentDefinition(
        id=IntentId.CARD_CHANGE_REQUEST,
        label="Card change request",
        description="Merchant requests card number update.",
        examples=["کارت جدید ثبت کنم"],
    ),
    IntentDefinition(
        id=IntentId.CONTRACT_APPROVAL,
        label="Contract approval",
        description="Merchant follows up on contract approval after IBAN.",
        examples=["شبا رو ثبت کردم، قرارداد کی تایید میشه"],
    ),
    IntentDefinition(
        id=IntentId.SETTLEMENT_INQUIRY,
        label="Settlement inquiry",
        description="Merchant asks about payout timing or settlement status.",
        examples=["تسویه این هفته کی واریز میشه؟"],
    ),
    IntentDefinition(
        id=IntentId.DOCUMENT_SUBMISSION,
        label="Document submission",
        description="Merchant asks how to upload or submit documents.",
        examples=["مدارک رو کجا آپلود کنم؟"],
    ),
    IntentDefinition(
        id=IntentId.ACCOUNT_ACCESS_ISSUE,
        label="Account access issue",
        description="Merchant has login or account access problems.",
        examples=["رمز عبورم کار نمیکنه"],
    ),
    IntentDefinition(
        id=IntentId.COMMISSION_INQUIRY,
        label="Commission inquiry",
        description="Merchant asks about fees or commission rates.",
        examples=["کارمزد فروش چقدره؟"],
    ),
    IntentDefinition(
        id=IntentId.SHIPPING_INQUIRY,
        label="Shipping inquiry",
        description="Merchant asks about shipping or logistics.",
        examples=["بسته رو چطور ارسال کنم؟"],
    ),
    IntentDefinition(
        id=IntentId.RETURN_REFUND_INQUIRY,
        label="Return refund inquiry",
        description="Merchant asks about returns or refunds.",
        examples=["مرجوعی مشتری رو چطور ثبت کنم؟"],
    ),
    IntentDefinition(
        id=IntentId.COMPLAINT_ORDER_FOLLOWUP,
        label="Complaint order followup",
        description=(
            "Seller responds to an admin complaint about an order and reports "
            "contact, return, refund, replacement, or resolution."
        ),
        examples=[
            "تماس گرفته شد، قرار شد کالا برگشت داده شود و هزینه برگشت داده شود"
        ],
    ),
    IntentDefinition(
        id=IntentId.TECHNICAL_BUG_REPORT,
        label="Technical bug report",
        description="Merchant reports a general technical issue or bug.",
        examples=["اپلیکیشن کرش میکنه"],
    ),
    IntentDefinition(
        id=IntentId.GENERAL_INQUIRY,
        label="General inquiry",
        description="Message does not match a specific intent.",
        examples=["سلام، یه سوال دارم"],
    ),
]

INTENT_BY_ID = {item.id: item for item in INTENT_TAXONOMY}
