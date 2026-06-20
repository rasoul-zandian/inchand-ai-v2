"""Evaluate intent classification on real seller tickets."""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.config import settings
from app.intent.classifier import classify_intent
from app.intent.real_ticket_cases import REAL_TICKET_CASES, RealTicketCase
from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult


@dataclass(frozen=True)
class TicketEvalResult:
    case_id: str
    expected_intent: IntentId
    predicted_intent: IntentId
    passed: bool
    evidence: list[str]
    context_flags: list[str]
    negative_intents: list[IntentId]
    fallback_reason: str | None
    taxonomy_gap_note: str | None = None


def is_live_eval_enabled() -> bool:
    return (
        os.getenv("RUN_LIVE_INTENT_EVAL", "").lower() in ("1", "true", "yes")
        and bool(os.getenv("OPENAI_API_KEY"))
        and os.getenv("INTENT_CLASSIFIER_PROVIDER", "rule") == "openai"
    )


def _expected_intents(case: RealTicketCase) -> tuple[IntentId, ...]:
    if case.accepted_intents:
        return case.accepted_intents
    return (case.expected_intent,)


def _case_passed(case: RealTicketCase, result: IntentClassificationResult) -> bool:
    if result.primary_intent not in _expected_intents(case):
        return False

    for flag in case.required_context_flags:
        if flag not in result.context_flags:
            return False

    for negative in case.required_negative_intents:
        if negative not in result.negative_intents:
            return False

    return True


def evaluate_case(case: RealTicketCase) -> TicketEvalResult:
    context = case.context or None
    result = classify_intent(case.message, conversation_context=context)
    passed = _case_passed(case, result)

    return TicketEvalResult(
        case_id=case.case_id,
        expected_intent=case.expected_intent,
        predicted_intent=result.primary_intent,
        passed=passed,
        evidence=result.evidence,
        context_flags=result.context_flags,
        negative_intents=result.negative_intents,
        fallback_reason=result.fallback_reason,
        taxonomy_gap_note=case.taxonomy_gap_note if not passed else None,
    )


def run_evaluation() -> list[TicketEvalResult]:
    return [evaluate_case(case) for case in REAL_TICKET_CASES]


def print_report(results: list[TicketEvalResult]) -> None:
    provider = settings.intent_classifier_provider
    mode = "live-openai" if is_live_eval_enabled() else provider
    passed_count = sum(1 for item in results if item.passed)

    print(f"Real ticket intent evaluation ({mode})")
    print(f"Passed {passed_count}/{len(results)}")
    print("")

    for item in results:
        status = "PASS" if item.passed else "FAIL"
        print(f"[{status}] {item.case_id}")
        print(f"  expected_intent: {item.expected_intent.value}")
        print(f"  predicted_intent: {item.predicted_intent.value}")
        print(f"  pass/fail: {status}")
        print(f"  evidence: {item.evidence}")
        print(f"  context_flags: {item.context_flags}")
        print(f"  negative_intents: {[i.value for i in item.negative_intents]}")
        if item.fallback_reason:
            print(f"  fallback_reason: {item.fallback_reason}")
        if item.taxonomy_gap_note:
            print(f"  taxonomy_gap: {item.taxonomy_gap_note}")
        print("")


def main() -> int:
    results = run_evaluation()
    print_report(results)
    passed_count = sum(1 for item in results if item.passed)
    return 0 if passed_count >= 7 else 1


if __name__ == "__main__":
    raise SystemExit(main())
