from hitl.console_ui import render_chat_html, render_console_html


def test_render_console_html_includes_header_fields() -> None:
    record = {
        "record_id": "48423:205050",
        "room_id": "48423",
        "shop_id": "7304",
        "target_message_id": "205050",
        "status": "pending_review",
        "created_at_jalali": "31-03-1404 12:15",
        "room_type": "support",
        "seller_message": "سلام",
        "conversation_context": [],
        "timeline_messages": [
            {
                "id": 202370,
                "sender": "admin",
                "role": "assistant",
                "content": "پشتیبانی",
                "created_at_jalali": "31-03-1404 10:13",
                "is_target": False,
            },
            {
                "id": 205050,
                "sender": "shop",
                "role": "user",
                "content": "سلام",
                "created_at_jalali": "31-03-1404 12:15",
                "is_target": True,
            },
        ],
        "pipeline": {
            "final_reply": "پاسخ",
            "primary_intent": "order_status_inquiry",
            "confidence": 0.87,
            "suggested_action": "reply_to_seller",
            "should_send": True,
            "selected_tools": [],
            "entities": {},
            "evidence": [],
            "warnings": [],
            "final_reply_source": "template",
            "needs_human_review": False,
        },
        "tool_output": [],
        "warnings": [],
        "send_log": [],
    }
    timeline = [
        {
            "message_id": "202370",
            "kind": "support",
            "content": "پشتیبانی",
            "timestamp": "31-03-1404 10:13",
            "is_target": False,
        },
        {
            "message_id": "205050",
            "kind": "seller",
            "content": "سلام",
            "timestamp": "31-03-1404 12:15",
            "is_target": True,
        },
    ]

    html = render_console_html(
        record,
        records=[record],
        timeline=timeline,
        active_tab="conversation",
        active_nav="pending_review",
        last_update="11:23:08",
        auto_refresh_on=True,
    )

    assert "48423" in html
    assert "205050" in html
    assert "pending_review" in html
    assert "Live HITL Review Console" in html
    assert "اطلاعات سفارش موجود نیست" in html


def test_render_chat_html_highlights_target() -> None:
    html = render_chat_html(
        [
            {
                "message_id": "100",
                "kind": "seller",
                "content": "target",
                "timestamp": "12:15",
                "is_target": True,
            }
        ]
    )
    assert "btarget" in html
    assert "پیام فعلی" in html
