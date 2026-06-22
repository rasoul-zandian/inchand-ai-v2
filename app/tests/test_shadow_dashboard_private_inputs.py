import json

from app.shadow.export_dashboard_private_inputs import export_private_input_from_room


def _room(**overrides) -> dict:
    room = {
        "id": 47918,
        "shop_id": 7711,
        "room_type": "support",
        "messages": [
            {
                "id": 202370,
                "sender": "admin",
                "content": "پاسخ پشتیبانی",
                "created_at": "2026-06-20T05:49:39Z",
            },
            {
                "id": 202375,
                "sender": "shop",
                "content": "متن پیام فروشنده",
                "created_at": "2026-06-20T05:50:12Z",
            },
            {
                "id": 202376,
                "sender": "admin",
                "content": "پیام بعد از هدف",
                "created_at": "2026-06-20T05:51:00Z",
            },
        ],
    }
    room.update(overrides)
    return room


def test_creates_seller_message() -> None:
    row = export_private_input_from_room(_room())

    assert row is not None
    assert row["room_id"] == "47918"
    assert row["target_message_id"] == "202375"
    assert row["seller_message"] == "متن پیام فروشنده"


def test_context_excludes_target_and_future_messages() -> None:
    row = export_private_input_from_room(_room())
    assert row is not None

    contents = [item["content"] for item in row.get("conversation_context", [])]
    assert "متن پیام فروشنده" not in contents
    assert "پیام بعد از هدف" not in contents
    assert contents == ["پاسخ پشتیبانی"]


def test_context_role_mapping_works() -> None:
    row = export_private_input_from_room(_room())
    assert row is not None

    context = row["conversation_context"]
    assert context[0]["role"] == "assistant"
    assert context[0]["timestamp"] == "2026-06-20T05:49:39Z"

    room = _room(
        messages=[
            {
                "id": 1,
                "sender": "shop",
                "content": "پیام قبلی",
                "created_at": "2026-06-20T05:40:00Z",
            },
            {
                "id": 2,
                "sender": "shop",
                "content": "پیام هدف",
            },
        ],
    )
    row = export_private_input_from_room(room)
    assert row is not None
    assert row["conversation_context"][0]["role"] == "user"
