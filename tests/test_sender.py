import json
from unittest.mock import patch

import pytest

from hitl.sender import (
    _create_message_url,
    build_admin_suggestion_content,
    build_admin_suggestion_meta,
    build_suggestion_content,
    parse_refer_to,
    send_reply,
    send_suggestion,
)


def _record(**overrides) -> dict:
    record = {
        "record_id": "48423:202375",
        "room_id": "48423",
        "target_message_id": "202375",
        "seller_message": "سلام، وضعیت سفارش INC-7342409 را لطفاً بررسی کنید.",
        "pipeline": {
            "final_reply": "پاسخ نهایی",
            "primary_intent": "shipping_inquiry",
            "confidence": 0.87,
            "suggested_action": "reply_to_seller",
            "final_reply_source": "template",
            "needs_human_review": False,
            "should_send": True,
            "entities": {"order_id": "INC-7342409"},
            "selected_tools": ["order_lookup", "iran_post_tracking"],
            "tool_status": {
                "order_lookup_executed": True,
                "order_lookup_success": True,
            },
            "warnings": [],
        },
        "tool_output": [
            {
                "order_id": "INC-7342409",
                "order_status": "ارسال شده",
                "parcel_status": "تحویل مرسوله",
                "tracking_code": "596760509400015050005114",
            }
        ],
    }
    record.update(overrides)
    return record


def test_parse_refer_to_empty_and_integer() -> None:
    assert parse_refer_to("") is None
    assert parse_refer_to("12345") == 12345
    assert parse_refer_to(99) == 99


def test_parse_refer_to_invalid_raises() -> None:
    with pytest.raises(ValueError, match="invalid_refer_to"):
        parse_refer_to("abc")


def test_send_reply_success() -> None:
    captured: dict = {}

    def fake_request(payload, timeout=10):
        captured["payload"] = payload
        return 200, {"id": 555}

    result = send_reply(_record(), refer_to=123, request_fn=fake_request)
    assert result["success"] is True
    assert captured["payload"]["type"] == 1
    assert captured["payload"]["refer_to"] == 123
    assert captured["payload"]["content"] == "پاسخ نهایی"


def test_send_suggestion_success() -> None:
    captured: dict = {}

    def fake_request(payload, timeout=10):
        captured["payload"] = payload
        return 200, {"id": 556}

    result = send_suggestion(_record(), request_fn=fake_request)
    assert result["success"] is True
    assert captured["payload"]["type"] == 3
    assert "AI intent=" not in captured["payload"]["content"]
    assert captured["payload"]["meta"]["message_kind"] == "ai_admin_suggestion"


def test_build_admin_suggestion_content_persian_card() -> None:
    content = build_admin_suggestion_content(_record())

    assert "AI intent=" not in content
    assert "🤖 پیشنهاد هوش مصنوعی برای ادمین" in content
    assert "پیگیری ارسال / مرسوله" in content
    assert "قابل پاسخ به فروشنده" in content
    assert "ابزارهای استفاده‌شده" in content
    assert "✓ جستجوی سفارش" in content
    assert "سفارش: INC-7342409" in content
    assert "<script" not in content


def test_build_admin_suggestion_content_shows_warnings() -> None:
    record = _record()
    record["pipeline"] = {**record["pipeline"], "warnings": ["missing_tracking_code"]}
    record["warnings"] = ["tool_timeout"]

    content = build_admin_suggestion_content(record)

    assert "هشدارها" in content
    assert "missing_tracking_code" in content
    assert "tool_timeout" in content


def test_build_admin_suggestion_meta_fields() -> None:
    meta = build_admin_suggestion_meta(_record())

    assert meta["source"] == "inchand_ai_v2"
    assert meta["mode"] == "live_hitl"
    assert meta["message_kind"] == "ai_admin_suggestion"
    assert meta["record_id"] == "48423:202375"
    assert meta["room_id"] == "48423"
    assert meta["target_message_id"] == "202375"
    assert meta["primary_intent"] == "shipping_inquiry"
    assert meta["confidence"] == 0.87
    assert meta["suggested_action"] == "reply_to_seller"
    assert meta["needs_human_review"] is False
    assert meta["should_send"] is True
    assert meta["entities"] == {"order_id": "INC-7342409"}
    assert meta["selected_tools"] == ["order_lookup", "iran_post_tracking"]
    assert meta["final_reply_source"] == "template"


def test_build_suggestion_content_alias() -> None:
    assert build_suggestion_content(_record()) == build_admin_suggestion_content(_record())


def test_send_reply_missing_token() -> None:
    with patch("hitl.sender.settings.inchand_api_key_value", ""):
        result = send_reply(_record())
    assert result["success"] is False
    assert result["error"] == "missing_token"


def test_send_reply_timeout() -> None:
    def fake_request(_payload, timeout=10):
        raise TimeoutError("timeout")

    result = send_reply(_record(), request_fn=fake_request)
    assert result["success"] is False
    assert result["error"] == "timeout"


def test_send_reply_api_failure() -> None:
    def fake_request(_payload, timeout=10):
        return 500, {"message": "internal"}

    result = send_reply(_record(), request_fn=fake_request)
    assert result["success"] is False
    assert result["error"] == "api_failure"


def test_create_message_url_internal_base(monkeypatch) -> None:
    monkeypatch.setenv("INCHAND_API_BASE_URL", "https://app.inchand.com/api/v1/internal")
    monkeypatch.delenv("HITL_INCHAND_CREATE_MESSAGE_PATH", raising=False)
    assert (
        _create_message_url()
        == "https://app.inchand.com/api/v1/internal/message/create"
    )


def test_create_message_url_host_base(monkeypatch) -> None:
    monkeypatch.setenv("INCHAND_API_BASE_URL", "https://app.inchand.com")
    monkeypatch.delenv("HITL_INCHAND_CREATE_MESSAGE_PATH", raising=False)
    assert (
        _create_message_url()
        == "https://app.inchand.com/api/v1/internal/message/create"
    )
