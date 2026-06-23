from hitl.app import (
    build_queue_dataframe,
    build_send_preview,
    build_timeline_messages,
    build_tool_views,
    format_queue_tools_label,
    sort_queue_records,
    truncate_preview,
    _classify_timeline_kind,
)


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


def test_build_timeline_messages_prefers_timeline_messages_field() -> None:
    record = {
        "record_id": "48423:202375",
        "target_message_id": "202375",
        "seller_message": "ignored",
        "timeline_messages": [
            {
                "id": 202370,
                "sender": "admin",
                "role": "assistant",
                "content": "پشتیبانی",
                "created_at": "2026-06-20T05:49:39Z",
                "created_at_jalali": "30-03-1405 09:19",
                "is_target": False,
            },
            {
                "id": 202375,
                "sender": "shop",
                "role": "user",
                "content": "متن پیام",
                "created_at": "2026-06-20T05:50:12Z",
                "created_at_jalali": "30-03-1405 09:20",
                "is_target": True,
            },
        ],
        "conversation_context": [],
        "pipeline": {"final_reply": "پاسخ AI"},
    }

    messages = build_timeline_messages(record)

    assert len(messages) == 3
    assert messages[0]["kind"] == "support"
    assert messages[1]["kind"] == "seller"
    assert messages[1]["is_target"] is True
    assert messages[2]["kind"] == "ai"


def test_build_timeline_messages_uses_sender_display_name() -> None:
    record = {
        "record_id": "49118:205134",
        "target_message_id": "205134",
        "timeline_messages": [
            {
                "id": 205140,
                "sender": "admin",
                "role": "assistant",
                "content": "admin reply",
                "sender_display_name": "رضا طاهری",
                "created_at": "2026-06-23 12:03:22",
                "created_at_jalali": "02-04-1405 12:03",
                "is_target": False,
            },
            {
                "id": 205134,
                "sender": "shop",
                "role": "user",
                "content": "target",
                "created_at": "2026-06-23 11:42:27",
                "created_at_jalali": "02-04-1405 11:42",
                "is_target": True,
            },
        ],
        "pipeline": {"final_reply": ""},
    }

    messages = build_timeline_messages(record)

    assert messages[0]["label"] == "رضا طاهری"
    assert messages[1]["label"] == "فروشنده"


def test_build_send_preview_matches_type_1_payload() -> None:
    record = {
        "record_id": "1:10",
        "pipeline": {
            "final_reply": "متن ارسالی",
            "primary_intent": "order_status_inquiry",
            "confidence": 0.91,
            "selected_tools": ["order_lookup", "iran_post_tracking"],
            "tool_status": {
                "order_lookup_executed": True,
                "order_lookup_success": True,
            },
        },
        "tool_output": [
            {
                "order_id": "INC-1",
                "order_status": "ارسال شده",
                "tracking_code": "123",
            }
        ],
    }

    preview = build_send_preview(record)

    assert preview["content"] == "متن ارسالی"
    assert preview["intent"] == "order_status_inquiry"
    assert preview["confidence"] == "91%"
    assert preview["tools"] == ["✓ order_lookup", "✓ iran_post_tracking"]


def test_sort_queue_records_pending_first_newest_first() -> None:
    records = [
        {"record_id": "a", "status": "sent", "created_at": "2026-06-20T10:00:00+00:00"},
        {"record_id": "b", "status": "pending_review", "created_at": "2026-06-20T09:00:00+00:00"},
        {"record_id": "c", "status": "pending_review", "created_at": "2026-06-20T11:00:00+00:00"},
    ]
    ordered = sort_queue_records(records)
    assert [record["record_id"] for record in ordered] == ["c", "b", "a"]


def test_truncate_preview() -> None:
    assert truncate_preview("short") == "short"
    assert truncate_preview("x" * 100).endswith("…")


def test_build_queue_dataframe_columns() -> None:
    records = [
        {
            "record_id": "1:10",
            "created_at_jalali": "01-01-1405 10:00",
            "room_id": "1",
            "shop_id": "2",
            "seller_message": "سلام این یک پیام تستی است",
            "status": "pending_review",
            "pipeline": {"primary_intent": "general_inquiry", "confidence": 0.8},
        }
    ]
    frame, record_ids = build_queue_dataframe(records)
    assert record_ids == ["1:10"]
    assert list(frame.columns) == [
        "Time",
        "Room",
        "Shop",
        "Intent",
        "Conf",
        "Status",
        "Tools",
        "Message",
    ]
    assert frame.iloc[0]["Conf"] == "80%"


def test_format_queue_tools_label() -> None:
    assert format_queue_tools_label({"pipeline": {}, "tool_output": []}) == "—"
    record = {
        "pipeline": {"selected_tools": ["order_lookup", "iran_post_tracking"]},
        "tool_output": [{"order_id": "INC-1"}],
    }
    assert format_queue_tools_label(record) == "🔧 order_lookup + tracking"


def test_build_tool_views_order_lookup_success() -> None:
    record = {
        "pipeline": {
            "selected_tools": ["order_lookup"],
            "tool_status": {
                "order_lookup_executed": True,
                "order_lookup_success": True,
                "order_lookup_error": None,
            },
            "warnings": [],
        },
        "tool_output": [
            {
                "order_id": "INC-7331208",
                "order_status": "ارسال شده",
                "parcel_status": "تحویل مرسوله",
                "tracking_code": "596760509400015050005114",
            }
        ],
        "warnings": [],
    }
    views = build_tool_views(record)
    order_view = next(view for view in views if view["name"] == "order_lookup")
    assert order_view["icon"] == "✓"
    assert "Order: INC-7331208" in order_view["summary"]
    assert "Status: ارسال شده" in order_view["summary"]


def test_build_tool_views_selected_but_not_executed() -> None:
    record = {
        "pipeline": {
            "selected_tools": ["product_lookup"],
            "tool_status": {},
            "warnings": [],
        },
        "tool_output": [],
        "warnings": [],
    }
    views = build_tool_views(record)
    product_view = next(view for view in views if view["name"] == "product_lookup")
    assert product_view["icon"] == "✗"
    assert product_view["status"] == "not_executed"
