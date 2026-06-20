from enum import Enum

from pydantic import BaseModel, Field

from app.intent.taxonomy import IntentId


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
    entities: dict[str, str] = Field(default_factory=dict)
    context_flags: list[str] = Field(default_factory=list)
    negative_intents: list[IntentId] = Field(default_factory=list)
    suggested_action: SuggestedAction
    fallback_reason: str | None = None
