from pydantic import BaseModel, Field

from app.intent.taxonomy import IntentId
from app.models.intent import SuggestedAction


class ReplyGenerationResult(BaseModel):
    text: str = Field(min_length=1)
    source: str = "template"
    primary_intent: IntentId
    suggested_action: SuggestedAction
    warnings: list[str] = Field(default_factory=list)


class ReplyEvaluationResult(BaseModel):
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)
