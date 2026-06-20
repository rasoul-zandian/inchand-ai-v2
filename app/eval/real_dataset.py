"""Real ticket dataset evaluation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from app.intent.taxonomy import IntentId
from app.models.messages import ConversationMessage
from app.pipeline.run_pipeline import run_pipeline
from app.reply.templates import FORBIDDEN_ONBOARDING_PHRASES


class RealDatasetCase(BaseModel):
    case_id: str
    seller_message: str
    conversation_context: list[ConversationMessage] = Field(default_factory=list)
    expected_intent: str
    expected_reply_contains: list[str] = Field(default_factory=list)
    expected_reply_not_contains: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("expected_intent")
    @classmethod
    def validate_expected_intent(cls, value: str) -> str:
        if value not in {intent.value for intent in IntentId}:
            raise ValueError(f"unknown expected_intent: {value}")
        return value


@dataclass(frozen=True)
class DatasetCaseResult:
    case_id: str
    expected_intent: str
    predicted_intent: str
    intent_pass: bool
    final_reply: str
    reply_pass: bool
    issues: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.intent_pass and self.reply_pass


@dataclass(frozen=True)
class DatasetEvalReport:
    total_cases: int
    intent_pass_count: int
    reply_pass_count: int
    failed_cases: list[DatasetCaseResult]
    results: list[DatasetCaseResult]


def load_jsonl(path: str | Path) -> list[RealDatasetCase]:
    file_path = Path(path)
    if not file_path.exists():
        return []

    cases: list[RealDatasetCase] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        cases.append(RealDatasetCase.model_validate(payload))
    return cases


def _reply_pass(case: RealDatasetCase, reply_text: str) -> tuple[bool, list[str]]:
    issues: list[str] = []
    for phrase in case.expected_reply_contains:
        if phrase not in reply_text:
            issues.append(f"missing_reply_phrase:{phrase}")
    for phrase in case.expected_reply_not_contains:
        if phrase in reply_text:
            issues.append(f"forbidden_reply_phrase:{phrase}")
    for phrase in FORBIDDEN_ONBOARDING_PHRASES:
        if phrase in reply_text:
            issues.append(f"forbidden_onboarding:{phrase}")
    return len(issues) == 0, issues


def evaluate_case(case: RealDatasetCase) -> DatasetCaseResult:
    context = case.conversation_context or None
    pipeline = run_pipeline(case.seller_message, conversation_context=context)
    predicted = pipeline.intent_result.primary_intent.value

    issues: list[str] = []
    intent_pass = predicted == case.expected_intent
    if not intent_pass:
        issues.append("intent_mismatch")

    reply_ok, reply_issues = _reply_pass(case, pipeline.final_reply.text)
    issues.extend(reply_issues)

    return DatasetCaseResult(
        case_id=case.case_id,
        expected_intent=case.expected_intent,
        predicted_intent=predicted,
        intent_pass=intent_pass,
        final_reply=pipeline.final_reply.text,
        reply_pass=reply_ok,
        issues=issues,
    )


def evaluate_dataset(cases: list[RealDatasetCase]) -> DatasetEvalReport:
    results = [evaluate_case(case) for case in cases]
    failed = [item for item in results if not item.passed]
    return DatasetEvalReport(
        total_cases=len(results),
        intent_pass_count=sum(1 for item in results if item.intent_pass),
        reply_pass_count=sum(1 for item in results if item.reply_pass),
        failed_cases=failed,
        results=results,
    )
