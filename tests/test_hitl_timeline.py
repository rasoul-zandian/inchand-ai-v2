from hitl.app import build_timeline_messages, _classify_timeline_kind


def test_build_timeline_messages_from_empty_context_uses_target_and_ai() -> None:
    record = {
        "record_id": "49091:205074",
        "target_message_id": "205074",
        "seller_message": "سلام",
        "created_at": "2026-06-23T06:11:16.465585+00:00",
        "conversation_context": [],
        "pipeline": {
            "final_reply": "پاسخ AI",
            "primary_intent": "general_inquiry",
        },
    }

    messages = build_timeline_messages(record)

    assert len(messages) == 2
    assert messages[0]["kind"] == "seller"
    assert messages[0]["is_target"] is True
    assert messages[0]["content"] == "سلام"
    assert messages[1]["kind"] == "ai"
    assert messages[1]["content"] == "پاسخ AI"


def test_build_timeline_messages_marks_target_in_context() -> None:
    record = {
        "record_id": "1:100",
        "target_message_id": "100",
        "seller_message": "ignored duplicate",
        "conversation_context": [
            {"id": 99, "sender": "admin", "content": "پشتیبانی", "created_at": "2026-06-20T05:49:40Z"},
            {"id": 100, "sender": "shop", "content": "فروشنده", "created_at": "2026-06-20T05:50:00Z"},
        ],
        "pipeline": {"final_reply": ""},
    }

    messages = build_timeline_messages(record)

    assert len(messages) == 2
    assert messages[0]["kind"] == "support"
    assert messages[1]["kind"] == "seller"
    assert messages[1]["is_target"] is True
    assert messages[1]["content"] == "فروشنده"


def test_build_timeline_messages_supports_role_based_context() -> None:
    record = {
        "record_id": "2:200",
        "target_message_id": "200",
        "seller_message": "current",
        "conversation_context": [
            {"role": "assistant", "content": "admin msg", "timestamp": "2026-06-20T05:49:40Z"},
            {"role": "user", "content": "seller msg", "timestamp": "2026-06-20T05:50:00Z"},
        ],
        "pipeline": {},
    }

    messages = build_timeline_messages(record)

    assert messages[0]["kind"] == "support"
    assert messages[1]["kind"] == "seller"


def test_classify_timeline_kind_maps_sender_and_role() -> None:
    assert _classify_timeline_kind({"sender": "shop"}) == "seller"
    assert _classify_timeline_kind({"sender": "admin"}) == "support"
    assert _classify_timeline_kind({"role": "user"}) == "seller"
    assert _classify_timeline_kind({"role": "assistant"}) == "support"
