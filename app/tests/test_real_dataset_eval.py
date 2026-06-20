import json
from pathlib import Path

import pytest

from app.config import settings
from app.eval.real_dataset import evaluate_dataset, load_jsonl
from app.eval.run_real_dataset import main as run_real_dataset_main
from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult, SuggestedAction
from app.models.pipeline import OrderLookupExecutionResult, PipelineResult
from app.models.reply import (
    ReplyEvaluationResult,
    ReplyGenerationResult,
    ReplyRevisionResult,
)
from app.models.tool import ToolSelectionResult


@pytest.fixture(autouse=True)
def force_rule_provider(monkeypatch):
    monkeypatch.setattr(settings, "intent_classifier_provider", "rule")


def test_runner_parses_jsonl(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "case_id": "case_a",
                "seller_message": "سلام",
                "conversation_context": [],
                "expected_intent": "general_inquiry",
                "expected_reply_contains": [],
                "expected_reply_not_contains": [],
                "notes": "",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    cases = load_jsonl(dataset)

    assert len(cases) == 1
    assert cases[0].case_id == "case_a"
    assert cases[0].expected_intent == "general_inquiry"


def test_empty_file_handled(tmp_path: Path) -> None:
    dataset = tmp_path / "empty.jsonl"
    dataset.write_text("", encoding="utf-8")

    report = evaluate_dataset(load_jsonl(dataset))

    assert report.total_cases == 0
    assert report.intent_pass_count == 0
    assert report.reply_pass_count == 0
    assert report.failed_cases == []


def test_one_passing_case_works(tmp_path: Path, monkeypatch) -> None:
    dataset = tmp_path / "one.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "case_id": "pass_case",
                "seller_message": "تسویه کی واریز میشه؟",
                "conversation_context": [],
                "expected_intent": "settlement_inquiry",
                "expected_reply_contains": ["تسویه"],
                "expected_reply_not_contains": [],
                "notes": "",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    pipeline = PipelineResult(
        intent_result=IntentClassificationResult(
            primary_intent=IntentId.SETTLEMENT_INQUIRY,
            confidence=0.9,
            suggested_action=SuggestedAction.REPLY_TO_SELLER,
        ),
        reply_result=ReplyGenerationResult(
            text="درخواست شما درباره وضعیت تسویه ثبت شد و در دست بررسی قرار گرفت.",
            primary_intent=IntentId.SETTLEMENT_INQUIRY,
            suggested_action=SuggestedAction.REPLY_TO_SELLER,
        ),
        evaluation_result=ReplyEvaluationResult(passed=True, score=1.0),
        revision_result=ReplyRevisionResult(
            revised=False,
            original_text="x",
            revised_text="x",
        ),
        tool_selection_result=ToolSelectionResult(),
        order_lookup_result=OrderLookupExecutionResult(executed=False),
        final_reply=ReplyGenerationResult(
            text="درخواست شما درباره وضعیت تسویه ثبت شد و در دست بررسی قرار گرفت.",
            primary_intent=IntentId.SETTLEMENT_INQUIRY,
            suggested_action=SuggestedAction.REPLY_TO_SELLER,
        ),
    )
    monkeypatch.setattr("app.eval.real_dataset.run_pipeline", lambda *_a, **_k: pipeline)

    report = evaluate_dataset(load_jsonl(dataset))

    assert report.total_cases == 1
    assert report.intent_pass_count == 1
    assert report.reply_pass_count == 1
    assert report.failed_cases == []
    assert run_real_dataset_main([str(dataset)]) == 0
