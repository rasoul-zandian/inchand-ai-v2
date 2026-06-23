import io
import json
import urllib.error
from pathlib import Path

import pytest

from hitl.poller import (
    _parse_room_response,
    _update_cursor,
    build_timeline_messages_from_room,
    fetch_new_messages,
    fetch_room,
    process_messages,
    run_poll_once,
)


def _shop_message(**overrides) -> dict:
    message = {
        "id": 202375,
        "room_id": 48423,
        "shop_id": 7304,
        "sender": "shop",
        "content": "متن پیام",
        "room_type": "support",
        "created_at": "2026-06-20T05:49:39Z",
    }
    message.update(overrides)
    return message


class _FakeResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args) -> None:
        return None


def _configure_fetch_env(monkeypatch) -> None:
    monkeypatch.setenv("INCHAND_API_BASE_URL", "https://app.inchand.com")
    monkeypatch.setenv("INCHAND_MESSAGES_ENDPOINT", "/api/v1/internal/messages")
    monkeypatch.setattr("hitl.poller.settings.inchand_api_key_name", "Authorization")
    monkeypatch.setattr("hitl.poller.settings.inchand_api_key_value", "test-token")


def test_process_messages_creates_pending_review_records(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HITL_STATE_DIR", str(tmp_path))

    messages = [
        {
            "id": 1001,
            "room_id": 2001,
            "shop_id": 3001,
            "sender": "shop",
            "content": "سلام",
            "room_type": "support",
        },
        {
            "id": 1002,
            "room_id": 2002,
            "shop_id": 3002,
            "sender": "admin",
            "content": "ignored",
        },
    ]

    def fake_pipeline(_request):
        return {
            "primary_intent": "general_inquiry",
            "confidence": 0.5,
            "final_reply": "reply",
            "final_reply_source": "template",
            "suggested_action": "reply_to_seller",
            "entities": {},
            "selected_tools": [],
            "evidence": [],
            "safe_tool_output": [],
            "warnings": [],
        }

    result = process_messages(
        messages,
        pipeline_fn=fake_pipeline,
        room_fetch_fn=lambda _room_id: None,
    )
    assert len(result["created"]) == 1
    assert result["created"][0]["status"] == "pending_review"
    assert result["created"][0]["target_message_id"] == "1001"


def test_run_poll_once_skips_when_lock_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HITL_STATE_DIR", str(tmp_path))
    lock = tmp_path / "poller.lock"
    lock.write_text("locked", encoding="utf-8")
    result = run_poll_once(fetch_fn=lambda _state: [])
    assert result["skipped"] is True


def test_fetch_new_messages_parses_data_wrapper(tmp_path, monkeypatch) -> None:
    _configure_fetch_env(monkeypatch)
    monkeypatch.setenv("HITL_STATE_DIR", str(tmp_path))
    captured: dict[str, str] = {}

    def fake_urlopen(request, timeout=10):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]
        body = json.dumps({"data": [_shop_message()]})
        return _FakeResponse(200, body)

    monkeypatch.setattr("hitl.poller.urllib.request.urlopen", fake_urlopen)

    messages = fetch_new_messages()
    assert len(messages) == 1
    assert messages[0]["id"] == 202375
    assert "after_message_id" not in captured["url"]
    assert captured["authorization"] == "test-token"


def test_fetch_new_messages_parses_list_response(tmp_path, monkeypatch) -> None:
    _configure_fetch_env(monkeypatch)
    monkeypatch.setenv("HITL_STATE_DIR", str(tmp_path))

    def fake_urlopen(_request, timeout=10):
        return _FakeResponse(200, json.dumps([_shop_message(id=99)]))

    monkeypatch.setattr("hitl.poller.urllib.request.urlopen", fake_urlopen)

    messages = fetch_new_messages()
    assert len(messages) == 1
    assert messages[0]["id"] == 99


def test_fetch_new_messages_sends_cursor_param(tmp_path, monkeypatch) -> None:
    _configure_fetch_env(monkeypatch)
    monkeypatch.setenv("HITL_STATE_DIR", str(tmp_path))
    state_file = tmp_path / "poller_state.json"
    state_file.write_text(
        json.dumps({"cursor_type": "after_message_id", "cursor_value": "100"}),
        encoding="utf-8",
    )
    captured: dict[str, str] = {}

    def fake_urlopen(request, timeout=10):
        captured["url"] = request.full_url
        return _FakeResponse(200, json.dumps({"messages": []}))

    monkeypatch.setattr("hitl.poller.urllib.request.urlopen", fake_urlopen)

    fetch_new_messages()
    assert "after_message_id=100" in captured["url"]
    assert "limit=50" in captured["url"]


def test_fetch_new_messages_uses_messages_path_for_internal_base(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HITL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("INCHAND_API_BASE_URL", "https://app.inchand.com/api/v1/internal")
    monkeypatch.setattr("hitl.poller.settings.inchand_api_key_name", "Authorization")
    monkeypatch.setattr("hitl.poller.settings.inchand_api_key_value", "test-token")
    monkeypatch.delenv("INCHAND_MESSAGES_ENDPOINT", raising=False)
    captured: dict[str, str] = {}

    def fake_urlopen(request, timeout=10):
        captured["url"] = request.full_url
        return _FakeResponse(200, json.dumps([]))

    monkeypatch.setattr("hitl.poller.urllib.request.urlopen", fake_urlopen)

    fetch_new_messages()
    assert captured["url"].startswith(
        "https://app.inchand.com/api/v1/internal/messages?"
    )


def test_fetch_new_messages_auth_missing(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HITL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("INCHAND_API_BASE_URL", "https://app.inchand.com")
    monkeypatch.setattr("hitl.poller.settings.inchand_api_key_value", "")

    messages = fetch_new_messages()
    output = capsys.readouterr().out

    assert messages == []
    assert "fetch_new_messages not configured" in output


def test_fetch_new_messages_api_error(tmp_path, monkeypatch, capsys) -> None:
    _configure_fetch_env(monkeypatch)
    monkeypatch.setenv("HITL_STATE_DIR", str(tmp_path))

    def fake_urlopen(_request, timeout=10):
        raise urllib.error.HTTPError(
            url="https://app.inchand.com/api/v1/internal/messages",
            code=500,
            msg="server error",
            hdrs=None,
            fp=io.BytesIO(b"error"),
        )

    monkeypatch.setattr("hitl.poller.urllib.request.urlopen", fake_urlopen)

    messages = fetch_new_messages()
    output = capsys.readouterr().out

    assert messages == []
    assert "fetch http status: 500" in output
    assert "fetch error: http_error (500)" in output


def test_update_cursor_uses_max_message_id_with_mixed_senders() -> None:
    messages = [
        {"id": 100, "sender": "shop"},
        {"id": 250, "sender": "admin"},
        {"id": 200, "sender": "shop"},
    ]
    state = {"cursor_type": "after_message_id", "cursor_value": None}

    updated = _update_cursor(state, messages)

    assert updated["cursor_value"] == "250"


def test_run_poll_once_updates_cursor_for_non_shop_messages(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HITL_STATE_DIR", str(tmp_path))

    messages = [
        {"id": 10, "sender": "admin", "room_id": 1, "shop_id": 1, "content": "x"},
        {"id": 20, "sender": "shop", "room_id": 1, "shop_id": 1, "content": "y", "room_type": "support"},
    ]

    def fake_pipeline(_request):
        return {
            "primary_intent": "general_inquiry",
            "confidence": 0.5,
            "final_reply": "reply",
            "final_reply_source": "template",
            "suggested_action": "reply_to_seller",
            "entities": {},
            "selected_tools": [],
            "evidence": [],
            "safe_tool_output": [],
            "warnings": [],
        }

    summary = run_poll_once(
        fetch_fn=lambda _state: messages,
        pipeline_fn=fake_pipeline,
        room_fetch_fn=lambda _room_id: None,
    )

    assert summary["cursor_value"] == "20"
    assert summary["ignored_sender_count"] == 1
    assert Path(tmp_path / "hitl_state.jsonl").exists()


def _sample_room(**overrides) -> dict:
    room = {
        "id": 48423,
        "shop_id": 7304,
        "room_type": "support",
        "messages": [
            {
                "id": 202370,
                "sender": "admin",
                "content": "پشتیبانی",
                "created_at": "2026-06-20T05:49:39Z",
            },
            {
                "id": 202375,
                "sender": "shop",
                "content": "متن پیام",
                "created_at": "2026-06-20T05:50:12Z",
            },
            {
                "id": 202380,
                "sender": "shop",
                "content": "future",
                "created_at": "2026-06-20T05:51:00Z",
            },
        ],
    }
    room.update(overrides)
    return room


def test_parse_room_response_shapes() -> None:
    room = _sample_room()
    assert _parse_room_response(room, 48423)[0] == room
    assert _parse_room_response({"data": room}, 48423)[0] == room
    assert _parse_room_response([room], 48423)[0] == room
    assert _parse_room_response({"data": [room]}, 48423)[0] == room
    assert _parse_room_response({"rooms": [room]}, 48423)[0] == room


def test_fetch_room_uses_settings_auth(tmp_path, monkeypatch) -> None:
    _configure_fetch_env(monkeypatch)
    captured: dict[str, str] = {}

    def fake_urlopen(request, timeout=10):
        captured["authorization"] = request.headers["Authorization"]
        return _FakeResponse(200, json.dumps({"data": _sample_room()}))

    monkeypatch.setattr("hitl.poller.urllib.request.urlopen", fake_urlopen)

    room = fetch_room(48423)
    assert room is not None
    assert captured["authorization"] == "test-token"


def test_hydrate_flow_uses_room_adapter(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HITL_STATE_DIR", str(tmp_path))
    captured: dict[str, object] = {}

    def fake_pipeline(request):
        captured["request"] = request
        return {
            "primary_intent": "general_inquiry",
            "confidence": 0.5,
            "final_reply": "reply",
            "final_reply_source": "template",
            "suggested_action": "reply_to_seller",
            "entities": {},
            "selected_tools": [],
            "evidence": [],
            "safe_tool_output": [],
            "warnings": [],
        }

    result = process_messages(
        [_shop_message()],
        pipeline_fn=fake_pipeline,
        room_fetch_fn=lambda _room_id: _sample_room(),
    )
    record = result["created"][0]
    request = captured["request"]

    assert request["seller_message"] == "متن پیام"
    assert len(request["conversation_context"]) == 1
    assert request["conversation_context"][0]["role"] == "assistant"
    assert len(record["timeline_messages"]) == 3
    assert record["timeline_messages"][1]["is_target"] is True
    assert record["timeline_messages"][1]["id"] == 202375
    assert record["timeline_messages"][-1]["content"] == "future"
    assert "room_hydration_failed" not in record["warnings"]


def test_timeline_includes_all_room_messages_and_caps_at_100() -> None:
    messages = [
        {
            "id": index,
            "sender": "admin" if index % 2 == 0 else "shop",
            "content": f"msg-{index}",
            "created_at": f"2026-06-20T05:{index % 60:02d}:00Z",
        }
        for index in range(1, 105)
    ]
    messages.append(
        {
            "id": 999,
            "sender": "shop",
            "content": "target",
            "created_at": "2026-06-20T06:00:00Z",
        }
    )
    room = {"id": 1, "messages": messages}

    timeline = build_timeline_messages_from_room(room, 999)

    assert len(timeline) == 100
    assert any(item["is_target"] for item in timeline)
    assert timeline[-1]["content"] == "target"
    assert timeline[-1]["is_target"] is True


def test_timeline_includes_messages_after_target_with_display_name() -> None:
    room = {
        "id": 49118,
        "messages": [
            {
                "id": 205134,
                "sender": "shop",
                "content": "target",
                "created_at": "2026-06-23 11:42:27",
            },
            {
                "id": 205140,
                "sender": "admin",
                "content": "admin reply",
                "created_at": "2026-06-23 12:03:22",
                "sender_name": "نسرین",
            },
            {
                "id": 205198,
                "sender": "shop",
                "content": "later shop",
                "created_at": "2026-06-23 17:01:40",
            },
        ],
    }

    timeline = build_timeline_messages_from_room(room, 205134)

    assert len(timeline) == 3
    assert timeline[1]["content"] == "admin reply"
    assert timeline[1]["sender_display_name"] == "نسرین"
    assert timeline[0]["is_target"] is True


def test_room_fetch_failure_falls_back_with_warning(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HITL_STATE_DIR", str(tmp_path))

    def fake_pipeline(_request):
        return {
            "primary_intent": "general_inquiry",
            "confidence": 0.5,
            "final_reply": "reply",
            "final_reply_source": "template",
            "suggested_action": "reply_to_seller",
            "entities": {},
            "selected_tools": [],
            "evidence": [],
            "safe_tool_output": [],
            "warnings": [],
        }

    result = process_messages(
        [_shop_message()],
        pipeline_fn=fake_pipeline,
        room_fetch_fn=lambda _room_id: None,
    )
    record = result["created"][0]

    assert record["status"] == "pending_review"
    assert "room_hydration_failed" in record["warnings"]
    assert record["timeline_messages"] == []
