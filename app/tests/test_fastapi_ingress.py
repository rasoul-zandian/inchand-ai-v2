import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.intent.taxonomy import IntentId
from app.main import app
from app.models.intent import IntentClassificationResult, SuggestedAction
from app.models.pipeline import OrderLookupExecutionResult, PipelineResult
from app.models.reply import (
    ReplyEvaluationResult,
    ReplyGenerationResult,
    ReplyRevisionResult,
)
from app.models.tool import ToolSelectionResult
from app.models.tool_contracts import ToolResult
from app.tools.order_lookup import ORDER_LOOKUP_TOOL


@pytest.fixture(autouse=True)
def force_rule_provider(monkeypatch):
    monkeypatch.setattr(settings, "intent_classifier_provider", "rule")
    monkeypatch.setattr("app.pipeline.run_pipeline.emit_pipeline_log", lambda _record: None)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _minimal_pipeline_result() -> PipelineResult:
    reply = ReplyGenerationResult(
        text="پاسخ",
        primary_intent=IntentId.GENERAL_INQUIRY,
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )
    return PipelineResult(
        intent_result=IntentClassificationResult(
            primary_intent=IntentId.GENERAL_INQUIRY,
            confidence=0.5,
            suggested_action=SuggestedAction.REPLY_TO_SELLER,
        ),
        reply_result=reply,
        evaluation_result=ReplyEvaluationResult(passed=True, score=1.0),
        revision_result=ReplyRevisionResult(
            revised=False,
            original_text="پاسخ",
            revised_text="پاسخ",
        ),
        tool_selection_result=ToolSelectionResult(selected_tools=[]),
        order_lookup_result=OrderLookupExecutionResult(executed=False),
        final_reply=reply,
    )


def test_post_valid_message_returns_200(client: TestClient) -> None:
    response = client.post(
        "/internal/pipeline/run",
        json={"seller_message": "سلام وضعیت سفارش INC-7342409 رو بررسی می‌کنید؟"},
    )

    assert response.status_code == 200


def test_response_contains_core_fields(client: TestClient) -> None:
    response = client.post(
        "/internal/pipeline/run",
        json={"seller_message": "رمز عبورم کار نمیکنه و نمیتونم وارد پنل بشم"},
    )

    body = response.json()
    assert body["primary_intent"] == IntentId.ACCOUNT_ACCESS_ISSUE.value
    assert body["final_reply"]
    assert body["needs_human_review"] is True


def test_metadata_is_accepted(client: TestClient, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_pipeline(*_args, metadata=None, **_kwargs):
        captured["metadata"] = metadata
        return _minimal_pipeline_result()

    monkeypatch.setattr("app.main.run_pipeline", fake_run_pipeline)

    response = client.post(
        "/internal/pipeline/run",
        json={
            "seller_message": "سلام",
            "metadata": {"case_id": "case-1", "room_id": "room-9"},
        },
    )

    assert response.status_code == 200
    assert captured["metadata"] == {"case_id": "case-1", "room_id": "room-9"}


def test_missing_seller_message_returns_validation_error(client: TestClient) -> None:
    response = client.post("/internal/pipeline/run", json={})

    assert response.status_code == 422


def test_response_does_not_include_raw_tool_data(client: TestClient, monkeypatch) -> None:
    def fake_order_lookup(*_args, **_kwargs):
        return OrderLookupExecutionResult(
            executed=True,
            tool_result=ToolResult(
                tool_name=ORDER_LOOKUP_TOOL,
                success=True,
                data={
                    "order_id": "INC-7342409",
                    "order_status": "ارسال شده",
                    "payment_status": "موفق",
                },
                summary="raw api summary should not leak",
            ),
        )

    monkeypatch.setattr(
        "app.pipeline.run_pipeline.run_selected_order_lookup",
        fake_order_lookup,
    )

    response = client.post(
        "/internal/pipeline/run",
        json={"seller_message": "سفارش INC-7342409 الان کجاست؟"},
    )

    assert response.status_code == 200
    body = response.json()
    serialized = response.text
    assert "data" not in body
    assert "summary" not in body
    assert "payment_status" not in serialized
    assert "raw api summary should not leak" not in serialized
    assert body["tool_status"]["order_lookup_executed"] is True
    assert body["tool_status"]["order_lookup_success"] is True
