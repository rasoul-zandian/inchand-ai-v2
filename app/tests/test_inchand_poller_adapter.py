import pytest

from app.integrations.inchand_poller_adapter import (
    build_pipeline_request_from_inchand_message,
    build_pipeline_request_from_inchand_room,
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


def test_shop_message_maps_to_pipeline_request() -> None:
    request = build_pipeline_request_from_inchand_message(_shop_message())

    assert request == {
        "seller_message": "متن پیام",
        "room_type": "support",
        "metadata": {
            "message_id": "202375",
            "room_id": "48423",
            "shop_id": "7304",
        },
    }


def test_numeric_ids_become_strings() -> None:
    request = build_pipeline_request_from_inchand_message(
        _shop_message(id=99, room_id=1001, shop_id=2002),
    )

    assert request["metadata"]["message_id"] == "99"
    assert request["metadata"]["room_id"] == "1001"
    assert request["metadata"]["shop_id"] == "2002"


def test_admin_message_raises_non_seller_message() -> None:
    with pytest.raises(ValueError, match="non_seller_message"):
        build_pipeline_request_from_inchand_message(
            _shop_message(sender="admin"),
        )


def test_context_sender_mapping_works() -> None:
    request = build_pipeline_request_from_inchand_message(
        _shop_message(),
        conversation_context=[
            {
                "id": 202370,
                "sender": "shop",
                "content": "پیام فروشنده",
                "created_at": "2026-06-20T05:40:00Z",
            },
            {
                "id": 202371,
                "sender": "admin",
                "content": "پاسخ پشتیبانی",
                "created_at": "2026-06-20T05:41:00Z",
            },
        ],
    )

    assert request["conversation_context"] == [
        {
            "role": "user",
            "content": "پیام فروشنده",
            "timestamp": "2026-06-20T05:40:00Z",
        },
        {
            "role": "assistant",
            "content": "پاسخ پشتیبانی",
            "timestamp": "2026-06-20T05:41:00Z",
        },
    ]


def test_target_message_removed_from_context() -> None:
    request = build_pipeline_request_from_inchand_message(
        _shop_message(),
        conversation_context=[
            {
                "id": 202375,
                "sender": "shop",
                "content": "پیام فعلی نباید در context باشد",
            },
            {
                "id": 202370,
                "sender": "admin",
                "content": "پیام قبلی",
            },
        ],
    )

    assert request["conversation_context"] == [
        {"role": "assistant", "content": "پیام قبلی"},
    ]


def test_missing_content_raises_validation_error() -> None:
    with pytest.raises(ValueError, match="missing_content"):
        build_pipeline_request_from_inchand_message(_shop_message(content=""))


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
                "id": 202371,
                "sender": "shop",
                "content": "پیام قبلی فروشنده",
                "created_at": "2026-06-20T05:50:00Z",
            },
            {
                "id": 202375,
                "sender": "shop",
                "content": "متن پیام هدف",
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


def test_room_builds_request_from_target_id() -> None:
    request = build_pipeline_request_from_inchand_room(_room(), 202375)

    assert request == {
        "seller_message": "متن پیام هدف",
        "room_type": "support",
        "metadata": {
            "message_id": "202375",
            "room_id": "47918",
            "shop_id": "7711",
        },
        "conversation_context": [
            {
                "role": "assistant",
                "content": "پاسخ پشتیبانی",
                "timestamp": "2026-06-20T05:49:39Z",
            },
            {
                "role": "user",
                "content": "پیام قبلی فروشنده",
                "timestamp": "2026-06-20T05:50:00Z",
            },
        ],
    }


def test_room_context_includes_only_messages_before_target() -> None:
    request = build_pipeline_request_from_inchand_room(_room(), 202375)

    assert len(request["conversation_context"]) == 2
    assert request["conversation_context"][0]["content"] == "پاسخ پشتیبانی"
    assert request["conversation_context"][1]["content"] == "پیام قبلی فروشنده"


def test_room_context_excludes_target_and_future_messages() -> None:
    request = build_pipeline_request_from_inchand_room(_room(), 202375)

    contents = [item["content"] for item in request["conversation_context"]]
    assert "متن پیام هدف" not in contents
    assert "پیام بعد از هدف" not in contents


def test_room_non_seller_target_raises() -> None:
    with pytest.raises(ValueError, match="non_seller_message"):
        build_pipeline_request_from_inchand_room(_room(), 202370)


def test_room_missing_target_raises() -> None:
    with pytest.raises(ValueError, match="missing_target_message"):
        build_pipeline_request_from_inchand_room(_room(), 999999)


def test_room_type_and_shop_id_mapped() -> None:
    request = build_pipeline_request_from_inchand_room(
        _room(room_type="complaint", shop_id=8800),
        202375,
    )

    assert request["room_type"] == "complaint"
    assert request["metadata"]["shop_id"] == "8800"

    request_no_shop = build_pipeline_request_from_inchand_room(
        _room(shop_id=None),
        202375,
    )
    assert "shop_id" not in request_no_shop["metadata"]
