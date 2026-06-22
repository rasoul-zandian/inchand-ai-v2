"""Map Inchand poller message payloads to V2 pipeline requests."""

_SELLER_SENDERS = {"shop", "seller"}
_ASSISTANT_SENDERS = {"admin", "support", "system"}


def _require_non_empty(value: object, error: str) -> str:
    if value is None or not str(value).strip():
        raise ValueError(error)
    return str(value)


def _map_context_sender(sender: str) -> str:
    if sender in _SELLER_SENDERS:
        return "user"
    if sender in _ASSISTANT_SENDERS:
        return "assistant"
    raise ValueError("unknown_context_sender")


def _convert_context_item(item: dict) -> dict:
    sender = str(item.get("sender", ""))
    role = _map_context_sender(sender)
    content = _require_non_empty(item.get("content"), "missing_content")

    converted = {"role": role, "content": content}
    created_at = item.get("created_at")
    if created_at is not None:
        converted["timestamp"] = str(created_at)
    return converted


def build_pipeline_request_from_inchand_message(
    message: dict,
    conversation_context: list | None = None,
) -> dict:
    sender = str(message.get("sender", ""))
    if sender not in _SELLER_SENDERS:
        raise ValueError("non_seller_message")

    seller_message = _require_non_empty(message.get("content"), "missing_content")
    message_id = message.get("id")
    if message_id is None:
        raise ValueError("missing_id")
    room_id = message.get("room_id")
    if room_id is None:
        raise ValueError("missing_room_id")

    request: dict = {
        "seller_message": seller_message,
        "metadata": {
            "message_id": str(message_id),
            "room_id": str(room_id),
        },
    }

    shop_id = message.get("shop_id")
    if shop_id is not None:
        request["metadata"]["shop_id"] = str(shop_id)

    room_type = message.get("room_type")
    if room_type is not None:
        request["room_type"] = str(room_type)

    if conversation_context:
        current_id = str(message_id)
        converted_context = []
        for item in conversation_context:
            item_id = item.get("id")
            if item_id is not None and str(item_id) == current_id:
                continue
            converted_context.append(_convert_context_item(item))
        if converted_context:
            request["conversation_context"] = converted_context

    return request


def build_pipeline_request_from_inchand_room(
    room: dict,
    target_message_id: str | int,
) -> dict:
    room_id = room.get("id")
    if room_id is None:
        raise ValueError("missing_room_id")

    messages = room.get("messages")
    if messages is None:
        raise ValueError("missing_messages")

    if target_message_id is None or not str(target_message_id).strip():
        raise ValueError("missing_target_id")

    target_id = str(target_message_id)
    target_message = None
    target_index = None
    for index, message in enumerate(messages):
        message_id = message.get("id")
        if message_id is not None and str(message_id) == target_id:
            target_message = message
            target_index = index
            break

    if target_message is None:
        raise ValueError("missing_target_message")

    sender = str(target_message.get("sender", ""))
    if sender not in _SELLER_SENDERS:
        raise ValueError("non_seller_message")

    seller_message = _require_non_empty(target_message.get("content"), "missing_content")
    target_msg_id = target_message.get("id")
    if target_msg_id is None:
        raise ValueError("missing_id")

    request: dict = {
        "seller_message": seller_message,
        "metadata": {
            "message_id": str(target_msg_id),
            "room_id": str(room_id),
        },
    }

    shop_id = room.get("shop_id")
    if shop_id is not None:
        request["metadata"]["shop_id"] = str(shop_id)

    room_type = room.get("room_type")
    if room_type is not None:
        request["room_type"] = str(room_type)

    if target_index > 0:
        converted_context = [
            _convert_context_item(message) for message in messages[:target_index]
        ]
        if converted_context:
            request["conversation_context"] = converted_context

    return request
