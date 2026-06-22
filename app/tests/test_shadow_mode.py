import json

import pytest

from app.config import settings
from app.intent.taxonomy import IntentId
from app.models.pipeline import OrderLookupExecutionResult
from app.models.tool_contracts import ToolResult
from app.shadow.run_shadow_mode import (
    extract_order_lookup_diagnostics,
    find_latest_seller_message_id,
    run_shadow_mode,
)
from app.tools.order_lookup import ORDER_LOOKUP_TOOL


@pytest.fixture(autouse=True)
def force_rule_provider(monkeypatch):
    monkeypatch.setattr(settings, "intent_classifier_provider", "rule")
    monkeypatch.setattr("app.pipeline.run_pipeline.emit_pipeline_log", lambda _record: None)


def _room(room_id: int, messages: list[dict], **overrides) -> dict:
    room = {
        "id": room_id,
        "shop_id": 7711,
        "room_type": "support",
        "messages": messages,
    }
    room.update(overrides)
    return room


def test_find_latest_seller_message_id() -> None:
    room = _room(
        1,
        [
            {"id": 10, "sender": "shop", "content": "اول"},
            {"id": 11, "sender": "admin", "content": "پاسخ"},
            {"id": 12, "sender": "seller", "content": "آخرین"},
        ],
    )

    assert find_latest_seller_message_id(room) == "12"


def test_non_seller_only_room_skipped(tmp_path) -> None:
    input_file = tmp_path / "rooms.jsonl"
    input_file.write_text(
        json.dumps(
            _room(
                99,
                [{"id": 1, "sender": "admin", "content": "فقط ادمین"}],
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "reports"

    summary = run_shadow_mode(input_file, output_dir)

    assert summary["total_rooms"] == 1
    assert summary["processed_rooms"] == 0
    assert summary["skipped_rooms"] == 1


def test_shadow_result_excludes_message_text(tmp_path) -> None:
    input_file = tmp_path / "rooms.jsonl"
    input_file.write_text(
        json.dumps(
            _room(
                1,
                [
                    {"id": 10, "sender": "admin", "content": "پاسخ پشتیبانی"},
                    {
                        "id": 11,
                        "sender": "shop",
                        "content": "رمز عبورم کار نمیکنه و نمیتونم وارد پنل بشم",
                    },
                ],
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "reports"

    run_shadow_mode(input_file, output_dir)

    results = [
        json.loads(line)
        for line in (output_dir / "shadow_mode_results.jsonl").read_text().splitlines()
        if line.strip()
    ]
    serialized = json.dumps(results, ensure_ascii=False)

    assert results[0]["target_message_id"] == "11"
    assert "seller_message" not in serialized
    assert "conversation_context" not in serialized
    assert "رمز عبورم" not in serialized


def test_summary_counts_auto_and_human_review(tmp_path) -> None:
    input_file = tmp_path / "rooms.jsonl"
    input_file.write_text(
        "\n".join(
            [
                json.dumps(
                    _room(
                        1,
                        [{"id": 11, "sender": "shop", "content": "سلام"}],
                    ),
                    ensure_ascii=False,
                ),
                json.dumps(
                    _room(
                        2,
                        [
                            {
                                "id": 21,
                                "sender": "shop",
                                "content": "رمز عبورم کار نمیکنه و نمیتونم وارد پنل بشم",
                            },
                        ],
                    ),
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "reports"

    summary = run_shadow_mode(input_file, output_dir)

    assert summary["processed_rooms"] == 2
    assert summary["auto_reply_count"] == 1
    assert summary["human_review_count"] == 1
    assert summary["send_gated_count"] == 1
    assert (output_dir / "shadow_mode_summary.json").is_file()
    assert (output_dir / "shadow_mode_summary.md").is_file()

    results = [
        json.loads(line)
        for line in (output_dir / "shadow_mode_results.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert results[1]["primary_intent"] == IntentId.ACCOUNT_ACCESS_ISSUE.value
    assert results[1]["needs_human_review"] is True


def test_shadow_result_includes_order_lookup_error_on_failure(tmp_path, monkeypatch) -> None:
    def fake_order_lookup(*_args, **_kwargs):
        return OrderLookupExecutionResult(
            executed=True,
            tool_result=ToolResult(
                tool_name=ORDER_LOOKUP_TOOL,
                success=False,
                error="missing_config",
                data={
                    "normalized_order_id": "INC-7342409",
                    "request_url_base": "https://app.inchand.com/api/v1/internal/orders/INC-7342409",
                },
            ),
        )

    monkeypatch.setattr(
        "app.pipeline.run_pipeline.run_selected_order_lookup",
        fake_order_lookup,
    )

    input_file = tmp_path / "rooms.jsonl"
    input_file.write_text(
        json.dumps(
            _room(
                1,
                [{"id": 11, "sender": "shop", "content": "سفارش INC-7342409 الان کجاست؟"}],
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "reports"

    run_shadow_mode(input_file, output_dir)

    results = [
        json.loads(line)
        for line in (output_dir / "shadow_mode_results.jsonl").read_text().splitlines()
        if line.strip()
    ]
    diagnostics = results[0]["order_lookup_diagnostics"]
    serialized = json.dumps(results, ensure_ascii=False)

    assert diagnostics["order_lookup_error"] == "missing_config"
    assert diagnostics["normalized_order_id"] == "INC-7342409"
    assert diagnostics["missing_config"] is True
    assert "request_url_base" not in serialized
    if settings.inchand_api_key_value:
        assert settings.inchand_api_key_value not in serialized


def test_extract_order_lookup_diagnostics_excludes_raw_payload() -> None:
    from app.models.intent import IntentClassificationResult, SuggestedAction
    from app.models.pipeline import PipelineResult
    from app.models.reply import (
        ReplyEvaluationResult,
        ReplyGenerationResult,
        ReplyRevisionResult,
    )
    from app.models.tool import ToolSelectionResult

    reply = ReplyGenerationResult(
        text="پاسخ",
        primary_intent=IntentId.ORDER_STATUS_INQUIRY,
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )
    result = PipelineResult(
        intent_result=IntentClassificationResult(
            primary_intent=IntentId.ORDER_STATUS_INQUIRY,
            confidence=0.9,
            suggested_action=SuggestedAction.REPLY_TO_SELLER,
        ),
        reply_result=reply,
        evaluation_result=ReplyEvaluationResult(passed=True, score=1.0),
        revision_result=ReplyRevisionResult(
            revised=False,
            original_text="پاسخ",
            revised_text="پاسخ",
        ),
        tool_selection_result=ToolSelectionResult(selected_tools=[ORDER_LOOKUP_TOOL]),
        order_lookup_result=OrderLookupExecutionResult(
            executed=True,
            tool_result=ToolResult(
                tool_name=ORDER_LOOKUP_TOOL,
                success=False,
                error="auth_error",
                data={
                    "normalized_order_id": "INC-1",
                    "http_status": "401",
                    "response_shape_summary": "dict:message",
                    "payment_status": "secret-should-not-appear",
                },
            ),
        ),
        final_reply=reply,
    )

    diagnostics = extract_order_lookup_diagnostics(result)
    serialized = json.dumps(diagnostics, ensure_ascii=False)

    assert diagnostics == {
        "order_lookup_error": "auth_error",
        "normalized_order_id": "INC-1",
        "http_status": "401",
        "response_shape_summary": "dict:message",
    }
    assert "payment_status" not in serialized
