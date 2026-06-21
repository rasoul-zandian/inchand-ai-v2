import json

import pytest

from app.config import settings
from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult, SuggestedAction
from app.models.pipeline import OrderLookupExecutionResult, PipelineResult
from app.models.reply import (
    ReplyEvaluationResult,
    ReplyGenerationResult,
    ReplyRevisionResult,
)
from app.models.tool import ToolSelectionResult
from app.models.tool_contracts import ToolRequest, ToolResult
from app.observability.pipeline_logging import build_pipeline_log_record
from app.pipeline.run_pipeline import run_pipeline
from app.tools.order_lookup import ORDER_LOOKUP_TOOL
from app.tools.selection import ORDER_LOOKUP


@pytest.fixture(autouse=True)
def force_rule_provider(monkeypatch):
    monkeypatch.setattr(settings, "intent_classifier_provider", "rule")


def _pipeline_result(
    *,
    needs_human_review: bool = False,
    entities: dict[str, str] | None = None,
    fallback_reason: str | None = None,
    order_lookup: OrderLookupExecutionResult | None = None,
    final_warnings: list[str] | None = None,
) -> PipelineResult:
    intent = IntentClassificationResult(
        primary_intent=IntentId.ORDER_STATUS_INQUIRY,
        confidence=0.9,
        entities=entities or {"order_id": "INC-7342409"},
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
        fallback_reason=fallback_reason,
    )
    reply = ReplyGenerationResult(
        text="وضعیت سفارش INC-7342409: ارسال شده.",
        primary_intent=IntentId.ORDER_STATUS_INQUIRY,
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
        source="template+enrichment",
        warnings=final_warnings or [],
    )
    return PipelineResult(
        intent_result=intent,
        reply_result=reply,
        evaluation_result=ReplyEvaluationResult(passed=True, score=1.0),
        revision_result=ReplyRevisionResult(
            revised=False,
            original_text=reply.text,
            revised_text=reply.text,
        ),
        tool_selection_result=ToolSelectionResult(selected_tools=[ORDER_LOOKUP]),
        order_lookup_result=order_lookup
        or OrderLookupExecutionResult(executed=False, tool_result=None),
        final_reply=reply,
        needs_human_review=needs_human_review,
    )


def test_log_record_contains_expected_fields() -> None:
    record = build_pipeline_log_record(
        _pipeline_result(),
        metadata={
            "case_id": "case-1",
            "room_id": "room-9",
            "message_id": "msg-3",
            "shop_id": "shop-7",
        },
    )

    assert record["event"] == "pipeline_completed"
    assert record["case_id"] == "case-1"
    assert record["room_id"] == "room-9"
    assert record["message_id"] == "msg-3"
    assert record["shop_id"] == "shop-7"
    assert record["primary_intent"] == IntentId.ORDER_STATUS_INQUIRY.value
    assert record["confidence"] == 0.9
    assert record["suggested_action"] == SuggestedAction.REPLY_TO_SELLER.value
    assert record["entities"] == {"order_id": "INC-7342409"}
    assert record["selected_tools"] == [ORDER_LOOKUP]
    assert record["final_reply_source"] == "template+enrichment"
    assert record["final_reply_warnings"] == []


def test_log_record_excludes_reply_and_seller_message() -> None:
    record = build_pipeline_log_record(_pipeline_result())
    serialized = json.dumps(record, ensure_ascii=False)

    assert "seller_message" not in record
    assert "final_reply" not in record
    assert "text" not in record
    assert "وضعیت سفارش INC-7342409" not in serialized


def test_log_record_includes_needs_human_review() -> None:
    record = build_pipeline_log_record(_pipeline_result(needs_human_review=True))
    assert record["needs_human_review"] is True


def test_log_record_includes_order_lookup_success() -> None:
    record = build_pipeline_log_record(
        _pipeline_result(
            order_lookup=OrderLookupExecutionResult(
                executed=True,
                tool_result=ToolResult(
                    tool_name=ORDER_LOOKUP_TOOL,
                    success=True,
                    data={"order_id": "INC-7342409", "order_status": "ارسال شده"},
                    summary="ok",
                ),
            ),
        ),
    )

    assert record["order_lookup_executed"] is True
    assert record["order_lookup_success"] is True
    assert record["order_lookup_error"] is None
    assert "data" not in record
    assert "ارسال شده" not in json.dumps(record, ensure_ascii=False)


def test_log_record_includes_order_lookup_failure() -> None:
    record = build_pipeline_log_record(
        _pipeline_result(
            order_lookup=OrderLookupExecutionResult(
                executed=True,
                tool_result=ToolResult(
                    tool_name=ORDER_LOOKUP_TOOL,
                    success=False,
                    error="order_not_found",
                ),
            ),
        ),
    )

    assert record["order_lookup_executed"] is True
    assert record["order_lookup_success"] is False
    assert record["order_lookup_error"] == "order_not_found"


def test_log_record_includes_fallback_reason_when_present() -> None:
    record = build_pipeline_log_record(
        _pipeline_result(fallback_reason="unknown_intent"),
    )
    assert record["fallback_reason"] == "unknown_intent"


def test_run_pipeline_emits_safe_log_line(capsys, monkeypatch) -> None:
    intent = IntentClassificationResult(
        primary_intent=IntentId.ORDER_STATUS_INQUIRY,
        confidence=0.9,
        entities={"order_id": "INC-7342409"},
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )
    monkeypatch.setattr("app.pipeline.run_pipeline.classify_intent", lambda *_a, **_k: intent)

    def fake_lookup(_request: ToolRequest) -> ToolResult:
        return ToolResult(
            tool_name=ORDER_LOOKUP_TOOL,
            success=True,
            data={"order_id": "INC-7342409", "found": "true", "order_status": "ارسال شده"},
            summary="ok",
        )

    run_pipeline(
        "سفارش INC-7342409 الان کجاست؟",
        metadata={"case_id": "case-42", "room_id": "room-1"},
        lookup_fn=fake_lookup,
    )

    log_line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(log_line)

    assert record["event"] == "pipeline_completed"
    assert record["case_id"] == "case-42"
    assert record["needs_human_review"] is False
    assert "سفارش INC-7342409" not in log_line
