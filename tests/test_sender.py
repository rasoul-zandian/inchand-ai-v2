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
        "shop_id": "7304",
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
                "payment_status": "موفق",
            }
        ],
    }
    record.update(overrides)
    return record


def _evidence_items() -> list[dict]:
    return [
        {
            "evidence_type": "order_status",
            "source_tool": "order_lookup",
            "confidence": 1.0,
            "summary": "وضعیت سفارش INC-7342409: ارسال شده",
            "data": {
                "order_id": "INC-7342409",
                "order_status": "ارسال شده",
                "payment_status": "موفق",
            },
        },
        {
            "evidence_type": "shipment_status",
            "source_tool": "order_lookup",
            "confidence": 1.0,
            "summary": "وضعیت مرسوله: تحویل مشتری",
            "data": {
                "tracking_code": "596760509400015050005114",
                "parcel_status": "تحویل مشتری",
            },
        },
        {
            "evidence_type": "tracking_status",
            "source_tool": "mahex_tracking",
            "confidence": 1.0,
            "summary": "وضعیت مرسوله ماهکس: تحویل مرسوله به گیرنده",
            "data": {
                "tracking_code": "10118730244480",
                "delivered": True,
            },
        },
    ]


def _evidence_record(**overrides) -> dict:
    record = _record()
    record["pipeline"] = {
        **record["pipeline"],
        "evidence_items": _evidence_items(),
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

    result = send_suggestion(_evidence_record(), request_fn=fake_request)
    assert result["success"] is True
    assert captured["payload"]["type"] == 3
    assert "AI intent=" not in captured["payload"]["content"]
    assert "<div" not in captured["payload"]["content"]
    assert "style=" not in captured["payload"]["content"]
    assert captured["payload"]["meta"]["schema"] == "admin_suggestion.v1"
    assert captured["payload"]["meta"]["message_kind"] == "ai_admin_suggestion"


def test_build_admin_suggestion_content_uses_evidence_summaries() -> None:
    content = build_admin_suggestion_content(_evidence_record())

    assert "🤖 پیشنهاد هوش مصنوعی" in content
    assert "شواهد بررسی‌شده" in content
    assert "✓ وضعیت سفارش INC-7342409: ارسال شده" in content
    assert "✓ وضعیت مرسوله: تحویل مشتری" in content
    assert "✓ وضعیت مرسوله ماهکس: تحویل مرسوله به گیرنده" in content
    assert "ابزارهای استفاده‌شده" not in content
    assert "اطلاعات سفارش" not in content


def test_build_admin_suggestion_content_has_no_raw_json() -> None:
    content = build_admin_suggestion_content(_evidence_record())

    assert "{" not in content
    assert "}" not in content
    assert '"data"' not in content
    assert "payment_status" not in content


def test_build_admin_suggestion_content_persian_labels_with_evidence() -> None:
    content = build_admin_suggestion_content(_evidence_record())

    assert "پیگیری ارسال / مرسوله" in content
    assert "پاسخ به فروشنده" in content
    assert "87%" in content
    assert "پیشنهاد سیستم" in content


def test_build_admin_suggestion_content_fallback_without_evidence() -> None:
    content = build_admin_suggestion_content(_record())

    assert "🤖 پیشنهاد هوش مصنوعی" in content
    assert "ابزارهای استفاده‌شده" in content
    assert "✓ جستجوی سفارش" in content
    assert "• شماره سفارش: INC-7342409" in content
    assert "سلام، وضعیت سفارش INC-7342409 را لطفاً بررسی کنید." in content
    assert "پاسخ نهایی" in content
    assert "شواهد بررسی‌شده" not in content


def test_build_admin_suggestion_content_empty_tools_fallback() -> None:
    record = _record()
    record["pipeline"] = {**record["pipeline"], "selected_tools": []}

    content = build_admin_suggestion_content(record)

    assert "ابزارهای استفاده‌شده: ندارد" in content
    assert "<div" not in content


def test_build_admin_suggestion_content_shows_translated_warnings_with_evidence() -> None:
    record = _evidence_record()
    record["pipeline"] = {
        **record["pipeline"],
        "warnings": ["unsupported_tracking_carrier:tipax"],
    }

    content = build_admin_suggestion_content(record)

    assert "هشدارها" in content
    assert "ابزار رهگیری برای این شرکت حمل فعال نیست" in content
    assert "unsupported_tracking_carrier" not in content


def test_build_admin_suggestion_content_fallback_shows_raw_warnings() -> None:
    record = _record()
    record["pipeline"] = {**record["pipeline"], "warnings": ["missing_tracking_code"]}
    record["warnings"] = ["tool_timeout"]

    content = build_admin_suggestion_content(record)

    assert "missing_tracking_code" in content
    assert "tool_timeout" in content


def test_build_admin_suggestion_content_empty_warnings() -> None:
    content = build_admin_suggestion_content(_evidence_record())

    warnings_section = content.split("هشدارها", 1)[1]
    assert "ندارد" in warnings_section


def test_build_admin_suggestion_meta_schema_and_evidence() -> None:
    meta = build_admin_suggestion_meta(_evidence_record())

    assert meta["schema"] == "admin_suggestion.v1"
    assert meta["source"] == "inchand_ai_v2"
    assert meta["mode"] == "live_hitl"
    assert meta["message_kind"] == "ai_admin_suggestion"
    assert meta["record_id"] == "48423:202375"
    assert meta["room_id"] == "48423"
    assert meta["shop_id"] == "7304"
    assert meta["target_message_id"] == "202375"
    assert meta["intent"] == {
        "id": "shipping_inquiry",
        "label_fa": "پیگیری ارسال / مرسوله",
        "confidence": 0.87,
    }
    assert meta["recommended_action"] == {
        "id": "reply_to_seller",
        "label_fa": "پاسخ به فروشنده",
        "should_send": True,
        "needs_human_review": False,
    }
    assert meta["entities"] == {"order_id": "INC-7342409"}
    assert len(meta["evidence"]) == 3
    assert meta["evidence"][0]["summary"] == "وضعیت سفارش INC-7342409: ارسال شده"
    assert meta["evidence"][0]["type"] == "order_status"
    assert meta["evidence"][0]["source_tool"] == "order_lookup"
    assert "payment_status" not in meta["evidence"][0]["data"]
    assert meta["tools"]["selected"] == ["order_lookup", "iran_post_tracking"]
    assert "order_lookup" in meta["tools"]["succeeded"]
    assert "mahex_tracking" in meta["tools"]["succeeded"]
    assert meta["reply_preview"] == "پاسخ نهایی"
    json.dumps(meta, ensure_ascii=False)


def test_build_admin_suggestion_meta_does_not_include_tool_output() -> None:
    meta = build_admin_suggestion_meta(_evidence_record())
    serialized = json.dumps(meta, ensure_ascii=False)

    assert "tool_output" not in serialized
    assert "payment_status" not in serialized
    assert meta["evidence"][0]["data"]["order_status"] == "ارسال شده"
    assert all("summary" in item for item in meta["evidence"])


def test_build_admin_suggestion_meta_fallback_empty_evidence() -> None:
    meta = build_admin_suggestion_meta(_record())

    assert meta["schema"] == "admin_suggestion.v1"
    assert meta["evidence"] == []
    assert meta["intent"]["id"] == "shipping_inquiry"
    assert meta["recommended_action"]["id"] == "reply_to_seller"


def test_build_admin_suggestion_meta_reads_nested_evidence_items() -> None:
    record = _record()
    record["pipeline"] = {
        **record["pipeline"],
        "evidence": {"items": _evidence_items()[:1]},
    }

    meta = build_admin_suggestion_meta(record)

    assert len(meta["evidence"]) == 1
    assert meta["evidence"][0]["summary"] == "وضعیت سفارش INC-7342409: ارسال شده"


def test_build_suggestion_content_alias() -> None:
    record = _evidence_record()
    assert build_suggestion_content(record) == build_admin_suggestion_content(record)


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
