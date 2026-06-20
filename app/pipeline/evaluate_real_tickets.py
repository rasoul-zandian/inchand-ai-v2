"""Evaluate the full pipeline on real and near-real seller tickets."""

from __future__ import annotations

from dataclasses import dataclass

from app.intent.taxonomy import IntentId
from app.models.pipeline import PipelineResult
from app.pipeline.pipeline_eval_cases import (
    KNOWN_CASE_COUNT,
    VARIATION_CASE_COUNT,
    PIPELINE_EVAL_CASES,
    PipelineEvalCase,
)
from app.pipeline.run_pipeline import run_pipeline
from app.reply.templates import FORBIDDEN_ONBOARDING_PHRASES


@dataclass(frozen=True)
class PipelineEvalResult:
    case_id: str
    expected_intent: IntentId
    predicted_intent: IntentId
    intent_pass: bool
    final_reply: str
    reply_pass: bool
    evaluation_pass: bool
    revision_applied: bool
    selected_tools: list[str]
    issues: list[str]


def _expected_intents(case: PipelineEvalCase) -> tuple[IntentId, ...]:
    if case.accepted_intents:
        return case.accepted_intents
    return (case.expected_intent,)


def _intent_pass(case: PipelineEvalCase, pipeline: PipelineResult) -> bool:
    predicted = pipeline.intent_result.primary_intent
    if predicted not in _expected_intents(case):
        return False
    if predicted in case.forbidden_predicted_intents:
        return False
    for flag in case.required_context_flags:
        if flag not in pipeline.intent_result.context_flags:
            return False
    for negative in case.required_negative_intents:
        if negative not in pipeline.intent_result.negative_intents:
            return False
    return True


def _asks_for_iban(reply_text: str) -> bool:
    lowered = reply_text.lower()
    return ("شبا" in lowered or "iban" in lowered) and (
        "ارسال" in lowered or "لطفاً" in lowered or "لطفا" in lowered
    )


def _reply_pass(case: PipelineEvalCase, reply_text: str) -> bool:
    if case.reply_exact is not None and reply_text != case.reply_exact:
        return False
    if case.reply_contains_any and not any(
        phrase in reply_text for phrase in case.reply_contains_any
    ):
        return False
    for phrase in case.reply_must_not_contain:
        if phrase in reply_text:
            return False
    if case.reply_must_not_ask_iban and _asks_for_iban(reply_text):
        return False
    for phrase in FORBIDDEN_ONBOARDING_PHRASES:
        if phrase in reply_text:
            return False
    return True


def evaluate_pipeline_case(case: PipelineEvalCase) -> PipelineEvalResult:
    context = case.context or None
    pipeline = run_pipeline(case.message, conversation_context=context)

    intent_ok = _intent_pass(case, pipeline)
    reply_ok = _reply_pass(case, pipeline.final_reply.text)
    issues: list[str] = []
    if not intent_ok:
        issues.append("intent_mismatch")
    if not reply_ok:
        issues.append("reply_mismatch")
    if not pipeline.evaluation_result.passed:
        issues.append("evaluation_failed")

    return PipelineEvalResult(
        case_id=case.case_id,
        expected_intent=case.expected_intent,
        predicted_intent=pipeline.intent_result.primary_intent,
        intent_pass=intent_ok,
        final_reply=pipeline.final_reply.text,
        reply_pass=reply_ok,
        evaluation_pass=pipeline.evaluation_result.passed,
        revision_applied=pipeline.revision_result.revised,
        selected_tools=list(pipeline.tool_selection_result.selected_tools),
        issues=issues,
    )


def run_evaluation() -> list[PipelineEvalResult]:
    return [evaluate_pipeline_case(case) for case in PIPELINE_EVAL_CASES]


def _case_overall_pass(result: PipelineEvalResult) -> bool:
    return result.intent_pass and result.reply_pass


def print_report(results: list[PipelineEvalResult]) -> None:
    known = [item for item in results if item.case_id.startswith("case_") and "_variation_" not in item.case_id]
    variations = [item for item in results if "_variation_" in item.case_id]

    known_pass = sum(1 for item in known if _case_overall_pass(item))
    variation_pass = sum(1 for item in variations if _case_overall_pass(item))
    total_pass = sum(1 for item in results if _case_overall_pass(item))

    print("Pipeline real ticket evaluation (rule mode)")
    print(f"Known cases passed: {known_pass}/{KNOWN_CASE_COUNT}")
    print(f"Variation cases passed: {variation_pass}/{VARIATION_CASE_COUNT}")
    print(f"Total passed: {total_pass}/{len(results)}")
    print("")

    for item in results:
        overall = _case_overall_pass(item)
        status = "PASS" if overall else "FAIL"
        print(f"[{status}] {item.case_id}")
        print(f"  expected_intent: {item.expected_intent.value}")
        print(f"  predicted_intent: {item.predicted_intent.value}")
        print(f"  intent_pass: {item.intent_pass}")
        print(f"  final_reply: {item.final_reply}")
        print(f"  reply_pass: {item.reply_pass}")
        print(f"  evaluation_pass: {item.evaluation_pass}")
        print(f"  revision_applied: {item.revision_applied}")
        print(f"  selected_tools: {item.selected_tools}")
        print(f"  issues: {item.issues}")
        print("")


def main() -> int:
    results = run_evaluation()
    print_report(results)

    known = [item for item in results if "_variation_" not in item.case_id]
    variations = [item for item in results if "_variation_" in item.case_id]
    known_pass = sum(1 for item in known if _case_overall_pass(item))
    variation_pass = sum(1 for item in variations if _case_overall_pass(item))

    if known_pass >= KNOWN_CASE_COUNT and variation_pass >= 7:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
