import json
from unittest.mock import patch

import pytest

from hitl.sender import build_suggestion_content, parse_refer_to, send_reply, send_suggestion


def _record() -> dict:
    return {
        "record_id": "48423:202375",
        "room_id": "48423",
        "pipeline": {
            "final_reply": "پاسخ نهایی",
            "primary_intent": "shipping_inquiry",
            "confidence": 0.87,
            "suggested_action": "reply_to_seller",
            "final_reply_source": "template",
            "entities": {"order_id": "INC-7342409"},
        },
    }


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
    def fake_request(payload, timeout=10):
        return 200, {"id": 556}

    result = send_suggestion(_record(), request_fn=fake_request)
    assert result["success"] is True
    assert "shipping_inquiry" in build_suggestion_content(_record())


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
