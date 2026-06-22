from enum import Enum

from pydantic import BaseModel, Field


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
    DELIVERY_CONFIRMATION_REQUEST = "delivery_confirmation_request"
    TECHNICAL_BUG_REPORT = "technical_bug_report"
    GENERAL_INQUIRY = "general_inquiry"


class SuggestedAction(str, Enum):
    REPLY_TO_SELLER = "reply_to_seller"
    REQUEST_MISSING_INFORMATION = "request_missing_information"
    HUMAN_FOLLOWUP = "human_followup"
    ESCALATE = "escalate"
    CLOSE_REQUEST = "close_request"


class IntentClassificationResult(BaseModel):
    primary_intent: IntentId
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    entities: dict[str, str | list[str]] = Field(default_factory=dict)
    context_flags: list[str] = Field(default_factory=list)
    negative_intents: list[IntentId] = Field(default_factory=list)
    suggested_action: SuggestedAction
    fallback_reason: str | None = None
