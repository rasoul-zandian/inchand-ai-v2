from pathlib import Path

import pytest

from app.config import settings
from app.eval.human_label_dataset import (
    evaluate_human_labels,
    load_human_label_workbook,
)
from app.models.intent import IntentClassificationResult, SuggestedAction
from app.models.pipeline import OrderLookupExecutionResult, PipelineResult
from app.models.reply import (
    ReplyEvaluationResult,
    ReplyGenerationResult,
    ReplyRevisionResult,
)
from app.models.tool import ToolSelectionResult
from app.intent.taxonomy import IntentId


WORKBOOK = Path("v2_human_label_50_with_context.xlsx")


@pytest.fixture(autouse=True)
def force_rule_provider(monkeypatch):
    monkeypatch.setattr(settings, "intent_classifier_provider", "rule")


def test_evaluator_loads_workbook() -> None:
    if not WORKBOOK.exists():
        pytest.skip("human label workbook missing")

    evaluable, skipped = load_human_label_workbook(WORKBOOK)

    assert len(evaluable) + len(skipped) > 0
    assert all(case.expected_intent for case in evaluable)
    assert all(case.seller_message for case in evaluable)


def test_accuracy_calculation_works(monkeypatch) -> None:
    from app.eval.human_label_dataset import HumanLabelCase

    cases = [
        HumanLabelCase(
            case_id="pass",
            seller_message="تسویه کی واریز میشه؟",
            expected_intent="settlement_inquiry",
        ),
        HumanLabelCase(
            case_id="fail",
            seller_message="آدرس فروشگاه رو عوض کنم",
            expected_intent="bank_account_change",
        ),
    ]

    def fake_pipeline(message, conversation_context=None, room_type=None):
        intent = (
            IntentId.SETTLEMENT_INQUIRY
            if "تسویه" in message
            else IntentId.SHOP_ADDRESS_UPDATE
        )
        reply = ReplyGenerationResult(
            text="reply",
            primary_intent=intent,
            suggested_action=SuggestedAction.REPLY_TO_SELLER,
        )
        return PipelineResult(
            intent_result=IntentClassificationResult(
                primary_intent=intent,
                confidence=0.9,
                suggested_action=SuggestedAction.REPLY_TO_SELLER,
            ),
            reply_result=reply,
            evaluation_result=ReplyEvaluationResult(passed=True, score=1.0),
            revision_result=ReplyRevisionResult(
                revised=False,
                original_text="reply",
                revised_text="reply",
            ),
            tool_selection_result=ToolSelectionResult(),
            order_lookup_result=OrderLookupExecutionResult(executed=False),
            final_reply=reply,
        )

    monkeypatch.setattr("app.eval.human_label_dataset.run_pipeline", fake_pipeline)

    report = evaluate_human_labels(cases)

    assert report.evaluated_cases == 2
    assert report.pass_count == 1
    assert report.fail_count == 1
    assert report.intent_accuracy == 0.5


def test_delivery_confirmation_rows_are_evaluated_not_skipped() -> None:
    if not WORKBOOK.exists():
        pytest.skip("human label workbook missing")

    evaluable, skipped = load_human_label_workbook(WORKBOOK)

    delivery_cases = [
        case for case in evaluable if case.expected_intent == "delivery_confirmation_request"
    ]
    skipped_intents = {case.expected_intent for case in skipped}

    assert len(delivery_cases) == 6
    assert "delivery_confirmation_request" not in skipped_intents
    assert skipped_intents == {"shop_activation_request"}


def test_empty_workbook_handled_safely() -> None:
    report = evaluate_human_labels([])

    assert report.total_cases == 0
    assert report.evaluated_cases == 0
    assert report.intent_accuracy == 0.0
    assert report.pass_count == 0
    assert report.fail_count == 0
    assert report.failures == []
