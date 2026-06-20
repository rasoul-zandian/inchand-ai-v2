from pydantic import BaseModel, Field

from app.intent.taxonomy import IntentId


class IntentClassificationResult(BaseModel):
    intent: IntentId
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1)
    settlement_context: bool = False
