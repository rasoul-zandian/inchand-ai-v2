"""Poll Inchand seller messages and enqueue HITL review records."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.integrations.inchand_poller_adapter import (
    build_pipeline_request_from_inchand_message,
    build_pipeline_request_from_inchand_room,
)
from app.config import settings

from hitl.jalali import to_jalali
from hitl.state import (
    acquire_poller_lock,
    append_record,
    exists_message,
    hitl_state_path,
    load_poller_state,
    load_records,
    poller_lock_exists,
    poller_state_path,
    release_poller_lock,
    rewrite_records,
    save_poller_state,
    state_dir,
)

FetchFn = Callable[[dict[str, Any]], list[dict[str, Any]]]
PipelineFn = Callable[[dict[str, Any]], dict[str, Any]]
RoomFetchFn = Callable[[str | int], dict[str, Any] | None]

_SHOP_SENDER = "shop"
_SELLER_SENDERS = {"shop", "seller"}
_TIMELINE_MAX_MESSAGES = 100


def _log(message: str) -> None:
    print(message, flush=True)


def _messages_endpoint() -> str:
    explicit = os.getenv("INCHAND_MESSAGES_ENDPOINT")
    if explicit:
        return explicit
    legacy = os.getenv("HITL_INCHAND_MESSAGES_PATH")
    if legacy:
        return legacy
    base = os.getenv("INCHAND_API_BASE_URL", "").rstrip("/")
    if base.endswith("/api/v1/internal"):
        return "/messages"
    return "/api/v1/internal/messages"


def _messages_url() -> str:
    base = os.getenv("INCHAND_API_BASE_URL", "").rstrip("/")
    path = _messages_endpoint()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


def _pipeline_url() -> str:
    return os.getenv(
        "HITL_PIPELINE_URL",
        "http://127.0.0.1:8000/internal/pipeline/run",
    )


def _fetch_configured() -> bool:
    base = os.getenv("INCHAND_API_BASE_URL", "")
    return bool(settings.inchand_api_key_value and base.startswith("http"))


def _cursor_query(cursor_type: str, cursor_value: str | None) -> dict[str, str]:
    if not cursor_value:
        return {}
    if cursor_type == "after_id":
        return {"after_id": cursor_value}
    if cursor_type == "after_timestamp":
        return {"after_timestamp": cursor_value}
    param = os.getenv("INCHAND_MESSAGES_CURSOR_PARAM", "after_message_id")
    return {param: cursor_value}


def _parse_messages_response(payload: Any) -> list[dict[str, Any]] | None:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data", payload.get("messages"))
        if isinstance(data, list):
            return data
    return None


def _cursor_message_id(cursor_value: Any) -> int | None:
    if cursor_value is None:
        return None
    text = str(cursor_value).strip()
    if not text or not text.isdigit():
        return None
    return int(text)


def filter_messages_after_cursor(
    messages: list[dict[str, Any]],
    cursor_value: Any,
) -> tuple[list[dict[str, Any]], int, int]:
    cursor_id = _cursor_message_id(cursor_value)
    if cursor_id is None:
        return messages, len(messages), 0

    new_messages: list[dict[str, Any]] = []
    old_count = 0
    for message in messages:
        message_id = message.get("id")
        if message_id is None:
            continue
        try:
            numeric_id = int(message_id)
        except (TypeError, ValueError):
            continue
        if numeric_id > cursor_id:
            new_messages.append(message)
        else:
            old_count += 1
    return new_messages, len(new_messages), old_count


def _log_client_side_cursor_filter(
    raw_messages: list[dict[str, Any]],
    cursor_value: Any,
) -> tuple[list[dict[str, Any]], int, int]:
    filtered, new_count, old_count = filter_messages_after_cursor(
        raw_messages,
        cursor_value,
    )
    _log(f"fetched count: {len(raw_messages)}")
    _log(f"cursor_value: {cursor_value}")
    _log(f"client-side new message count: {new_count}")
    _log(f"filtered old message count: {old_count}")
    return filtered, new_count, old_count


def _fetch_messages_raw(
    poller_state: dict[str, Any],
    *,
    fetch_fn: FetchFn | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    cursor_type = str(poller_state.get("cursor_type", "after_message_id"))
    cursor_value = poller_state.get("cursor_value")

    if fetch_fn is not None:
        return fetch_fn(poller_state)

    if not _fetch_configured():
        _log("fetch_new_messages not configured")
        return []

    params = {"limit": str(limit), **_cursor_query(cursor_type, cursor_value)}
    url = f"{_messages_url()}?{urllib.parse.urlencode(params)}"
    path = urllib.parse.urlparse(url).path
    _log(f"fetch path: {path}")
    _log(f"cursor before: {cursor_value}")

    request = urllib.request.Request(
        url,
        headers={settings.inchand_api_key_name: settings.inchand_api_key_value},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            status = getattr(response, "status", 200)
    except TimeoutError:
        _log_fetch_error("timeout")
        return []
    except urllib.error.HTTPError as exc:
        _log(f"fetch http status: {exc.code}")
        _log_fetch_error("http_error", str(exc.code))
        return []
    except urllib.error.URLError as exc:
        _log_fetch_error("network_error", type(exc).__name__)
        return []

    _log(f"fetch http status: {status}")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        _log_fetch_error("invalid_json")
        return []

    messages = _parse_messages_response(payload)
    if messages is None:
        _log_fetch_error("unexpected_response_shape")
        return []

    return messages


def fetch_new_messages(
    poller_state: dict[str, Any] | None = None,
    *,
    fetch_fn: FetchFn | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    state = poller_state or load_poller_state()
    raw_messages = _fetch_messages_raw(state, fetch_fn=fetch_fn, limit=limit)
    filtered, _, _ = _log_client_side_cursor_filter(raw_messages, state.get("cursor_value"))
    return filtered


def _log_fetch_error(category: str, detail: str = "") -> None:
    if detail:
        _log(f"fetch error: {category} ({detail})")
    else:
        _log(f"fetch error: {category}")


def _rooms_endpoint() -> str:
    explicit = os.getenv("INCHAND_ROOMS_ENDPOINT")
    if explicit:
        return explicit
    base = os.getenv("INCHAND_API_BASE_URL", "").rstrip("/")
    if base.endswith("/api/v1/internal"):
        return "/rooms"
    return "/api/v1/internal/rooms"


def _rooms_url(room_id: str | int) -> str:
    base = os.getenv("INCHAND_API_BASE_URL", "").rstrip("/")
    path = _rooms_endpoint()
    if not path.startswith("/"):
        path = f"/{path}"
    if os.getenv("INCHAND_ROOM_FETCH_STYLE", "query") == "path":
        return f"{base}{path.rstrip('/')}/{room_id}"
    param = os.getenv("INCHAND_ROOM_ID_PARAM", "room_id")
    return f"{base}{path}?{urllib.parse.urlencode({param: str(room_id)})}"


def _room_id_matches(room: dict[str, Any], room_id_text: str) -> bool:
    room_key = room.get("id")
    return room_key is not None and str(room_key) == room_id_text


def _room_dicts_from_list(items: list[Any]) -> list[dict[str, Any]]:
    return [item for item in items if isinstance(item, dict)]


def _find_room_in_list(
    rooms: list[dict[str, Any]],
    room_id_text: str,
) -> dict[str, Any] | None:
    for room in rooms:
        if _room_id_matches(room, room_id_text):
            return room
    return None


def _room_ids_from_list(rooms: list[dict[str, Any]], *, limit: int = 10) -> list[str]:
    ids: list[str] = []
    for room in rooms:
        room_key = room.get("id")
        if room_key is None:
            continue
        ids.append(str(room_key))
        if len(ids) >= limit:
            break
    return ids


def _collect_room_ids_from_payload(payload: Any, *, limit: int = 10) -> list[str]:
    if isinstance(payload, list):
        return _room_ids_from_list(_room_dicts_from_list(payload), limit=limit)

    if not isinstance(payload, dict):
        return []

    data = payload.get("data")
    if isinstance(data, list):
        return _room_ids_from_list(_room_dicts_from_list(data), limit=limit)
    if isinstance(data, dict) and data.get("id") is not None:
        return [str(data.get("id"))]

    rooms_value = payload.get("rooms")
    if isinstance(rooms_value, list):
        return _room_ids_from_list(_room_dicts_from_list(rooms_value), limit=limit)

    if payload.get("id") is not None:
        return [str(payload.get("id"))]
    return []


def _log_unexpected_room_response(payload: Any, room_id: str | int) -> None:
    _log(f"room fetch unexpected shape for room_id: {room_id}")
    _log(f"payload type: {type(payload).__name__}")
    if isinstance(payload, dict):
        _log(f"payload keys: {sorted(payload.keys())}")
    elif isinstance(payload, list):
        _log(f"payload list length: {len(payload)}")
        if payload:
            first = payload[0]
            if isinstance(first, dict):
                _log(f"first item keys: {sorted(first.keys())}")
    room_ids = _collect_room_ids_from_payload(payload)
    if room_ids:
        _log(f"room ids found: {room_ids}")


def _parse_room_response(
    payload: Any,
    room_id: str | int,
) -> tuple[dict[str, Any] | None, str]:
    room_id_text = str(room_id)

    if isinstance(payload, dict) and isinstance(payload.get("messages"), list):
        if payload.get("id") is None or str(payload.get("id")) == room_id_text:
            return payload, "room_object"
        return None, "room_not_found_in_response"

    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            if data.get("id") is None or str(data.get("id")) == room_id_text:
                return data, "data_object"
            return None, "room_not_found_in_response"

        if isinstance(data, list):
            rooms = _room_dicts_from_list(data)
            found = _find_room_in_list(rooms, room_id_text)
            if found is not None:
                shape = "laravel_paginated_list" if "meta" in payload or "links" in payload else "data_list"
                return found, shape
            if rooms or data == []:
                return None, "room_not_found_in_response"

        rooms_value = payload.get("rooms")
        if isinstance(rooms_value, list):
            rooms = _room_dicts_from_list(rooms_value)
            found = _find_room_in_list(rooms, room_id_text)
            if found is not None:
                return found, "rooms_list"
            if rooms or rooms_value == []:
                return None, "room_not_found_in_response"

    if isinstance(payload, list):
        rooms = _room_dicts_from_list(payload)
        found = _find_room_in_list(rooms, room_id_text)
        if found is not None:
            return found, "list"
        return None, "room_not_found_in_response"

    return None, "unexpected_response_shape"


def fetch_room(room_id: str | int) -> dict[str, Any] | None:
    if not _fetch_configured():
        return None

    url = _rooms_url(room_id)
    path = urllib.parse.urlparse(url).path
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    room_param = os.getenv("INCHAND_ROOM_ID_PARAM", "room_id")
    room_param_value = query.get(room_param, [str(room_id)])[0]
    _log(f"fetch room path: {path}")
    _log(f"room_id: {room_id}")
    _log(f"room fetch query: {room_param}={room_param_value}")

    request = urllib.request.Request(
        url,
        headers={settings.inchand_api_key_name: settings.inchand_api_key_value},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            status = getattr(response, "status", 200)
    except TimeoutError:
        _log_fetch_error("room_timeout")
        return None
    except urllib.error.HTTPError as exc:
        _log(f"room fetch http status: {exc.code}")
        _log_fetch_error("room_http_error", str(exc.code))
        return None
    except urllib.error.URLError as exc:
        _log_fetch_error("room_network_error", type(exc).__name__)
        return None

    _log(f"room fetch http status: {status}")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        _log_fetch_error("room_invalid_json")
        return None

    room, shape = _parse_room_response(payload, room_id)
    _log(f"room response shape: {shape}")
    if room is None:
        if shape == "room_not_found_in_response":
            _log_fetch_error("room_not_found_in_response")
        else:
            _log_unexpected_room_response(payload, room_id)
            _log_fetch_error("room_unexpected_response_shape")
        return None

    messages = room.get("messages") or []
    message_count = len(messages) if isinstance(messages, list) else 0
    _log(f"room messages count: {message_count}")
    return room


def _sender_to_role(sender: str) -> str:
    if sender in _SELLER_SENDERS:
        return "user"
    return "assistant"


def _sort_room_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(message: dict[str, Any]) -> tuple[str, int]:
        created_at = message.get("created_at")
        message_id = message.get("id")
        numeric_id = int(message_id) if message_id is not None else 0
        return (str(created_at or ""), numeric_id)

    return sorted(
        [message for message in messages if isinstance(message, dict)],
        key=sort_key,
    )


def _extract_sender_display_name(message: dict[str, Any]) -> str | None:
    for key in ("sender_display_name", "sender_name", "display_name", "name"):
        value = message.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    for nested_key in ("user", "admin", "sender_user", "created_by"):
        nested = message.get(nested_key)
        if not isinstance(nested, dict):
            continue
        for key in ("display_name", "name", "full_name"):
            value = nested.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return None


def build_timeline_messages_from_room(
    room: dict[str, Any],
    target_message_id: str | int,
    *,
    max_messages: int = _TIMELINE_MAX_MESSAGES,
) -> list[dict[str, Any]]:
    messages = room.get("messages")
    if not isinstance(messages, list):
        return []

    target_id = str(target_message_id)
    ordered = _sort_room_messages(messages)
    if not any(
        message.get("id") is not None and str(message.get("id")) == target_id
        for message in ordered
    ):
        return []

    selected = ordered
    if len(selected) > max_messages:
        selected = selected[-max_messages:]

    timeline: list[dict[str, Any]] = []
    for message in selected:
        message_id = message.get("id")
        sender = str(message.get("sender", ""))
        created_at = message.get("created_at")
        created_at_text = str(created_at) if created_at is not None else None
        display_name = _extract_sender_display_name(message)
        timeline.append(
            {
                "id": message_id,
                "sender": sender,
                "role": _sender_to_role(sender),
                "content": str(message.get("content", "")),
                "created_at": created_at_text,
                "created_at_jalali": to_jalali(created_at_text) if created_at_text else "",
                "sender_display_name": display_name,
                "is_target": message_id is not None and str(message_id) == target_id,
            }
        )
    return timeline


def update_room_timeline_for_existing_records(
    room_id: str | int,
    room: dict[str, Any],
    *,
    room_last_message_id: str | int | None = None,
    state_path: Path | None = None,
) -> int:
    file_path = state_path or hitl_state_path()
    records = load_records(file_path)
    room_id_text = str(room_id)
    synced_at = datetime.now(timezone.utc).isoformat()
    updated = 0

    for index, record in enumerate(records):
        if str(record.get("room_id")) != room_id_text:
            continue
        target_id = record.get("target_message_id")
        if target_id is None:
            continue
        timeline_messages = build_timeline_messages_from_room(room, target_id)
        if not timeline_messages:
            continue
        records[index] = {
            **record,
            "timeline_messages": timeline_messages,
            "room_last_message_id": (
                str(room_last_message_id) if room_last_message_id is not None else None
            ),
            "room_last_synced_at": synced_at,
        }
        updated += 1

    if updated:
        rewrite_records(records, file_path)
    return updated


def _flat_message_context(message: dict[str, Any]) -> list[dict[str, Any]] | None:
    context = message.get("conversation_context")
    if not isinstance(context, list):
        context = message.get("context")
    if not isinstance(context, list):
        return None
    return context


def _prepare_hydrated_processing(
    message: dict[str, Any],
    *,
    room_fetch_fn: RoomFetchFn | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    message_id = message.get("id")
    room_id = message.get("room_id")
    flat_context = _flat_message_context(message)
    fetcher = room_fetch_fn or fetch_room

    if room_id is not None and message_id is not None:
        room = fetcher(room_id)
        if room is not None:
            try:
                pipeline_request = build_pipeline_request_from_inchand_room(
                    room,
                    message_id,
                )
                conversation_context = list(
                    pipeline_request.get("conversation_context", [])
                )
                timeline_messages = build_timeline_messages_from_room(room, message_id)
                return pipeline_request, conversation_context, timeline_messages, []
            except ValueError:
                pass

    pipeline_request = build_pipeline_request_from_inchand_message(
        message,
        conversation_context=flat_context,
    )
    return (
        pipeline_request,
        _last_context_messages(flat_context),
        [],
        ["room_hydration_failed"],
    )


def load_messages_from_file(path: str) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        _log_fetch_error("file_not_found", file_path.name)
        return []

    latest: dict[str, Any] | None = None
    latest_created = ""

    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        room = json.loads(line)
        room_id = room.get("id")
        shop_id = room.get("shop_id")
        room_type = room.get("room_type")
        messages = room.get("messages") or []
        if not isinstance(messages, list):
            continue

        shop_messages = [
            message
            for message in messages
            if str(message.get("sender", "")) == _SHOP_SENDER
        ]
        if not shop_messages:
            continue

        target = max(
            shop_messages,
            key=lambda item: str(item.get("created_at", "")),
        )
        created_at = str(target.get("created_at", ""))
        if latest is not None and created_at <= latest_created:
            continue

        target_id = target.get("id")
        if target_id is None or room_id is None:
            continue

        prior = []
        for message in messages:
            message_id = message.get("id")
            if message_id is not None and str(message_id) == str(target_id):
                break
            prior.append(message)

        latest = {
            "id": target_id,
            "room_id": room_id,
            "shop_id": shop_id,
            "sender": _SHOP_SENDER,
            "content": target.get("content", ""),
            "room_type": room_type,
            "conversation_context": prior,
            "created_at": created_at,
        }
        latest_created = created_at

    if latest is None:
        _log("from-file: no shop messages found")
        return []
    return [latest]


def _last_context_messages(
    conversation_context: list[dict[str, Any]] | None,
    *,
    max_messages: int = 10,
) -> list[dict[str, Any]]:
    if not conversation_context:
        return []
    return conversation_context[-max_messages:]


def call_pipeline(
    pipeline_request: dict[str, Any],
    *,
    pipeline_fn: PipelineFn | None = None,
) -> dict[str, Any]:
    if pipeline_fn is not None:
        return pipeline_fn(pipeline_request)

    url = _pipeline_url()
    body = json.dumps(pipeline_request, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except TimeoutError as exc:
        raise TimeoutError("pipeline_timeout") from exc
    except urllib.error.URLError as exc:
        raise urllib.error.URLError("pipeline_network_error") from exc

    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("invalid_pipeline_response")
    return parsed


def build_review_record(
    message: dict[str, Any],
    pipeline_response: dict[str, Any],
    conversation_context: list[dict[str, Any]] | None = None,
    *,
    timeline_messages: list[dict[str, Any]] | None = None,
    record_warnings: list[str] | None = None,
) -> dict[str, Any]:
    message_id = str(message["id"])
    room_id = str(message["room_id"])
    now = datetime.now(timezone.utc)
    record_id = f"{room_id}:{message_id}"
    warnings = list(record_warnings or [])
    for item in pipeline_response.get("warnings", []):
        if item not in warnings:
            warnings.append(item)
    return {
        "record_id": record_id,
        "target_message_id": message_id,
        "room_id": room_id,
        "shop_id": str(message.get("shop_id", "")),
        "room_type": str(message.get("room_type", "")),
        "status": "pending_review",
        "created_at": now.isoformat(),
        "created_at_jalali": to_jalali(now),
        "seller_message": str(message.get("content", "")),
        "conversation_context": list(conversation_context or []),
        "timeline_messages": list(timeline_messages or []),
        "pipeline": pipeline_response,
        "tool_output": pipeline_response.get("safe_tool_output", []),
        "warnings": warnings,
        "feedback": None,
        "send_log": [],
    }


def _message_id_sort_key(message_id: Any) -> tuple[int, int | str]:
    text = str(message_id)
    if text.isdigit():
        return (0, int(text))
    return (1, text)


def _max_message_id(messages: list[dict[str, Any]]) -> str | None:
    with_ids = [message for message in messages if message.get("id") is not None]
    if not with_ids:
        return None
    best = max(with_ids, key=lambda message: _message_id_sort_key(message["id"]))
    return str(best["id"])


def _update_cursor(
    poller_state: dict[str, Any],
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    if not messages:
        return poller_state

    cursor_type = str(poller_state.get("cursor_type", "after_message_id"))
    updated = dict(poller_state)
    if cursor_type == "after_timestamp":
        last = max(messages, key=lambda item: str(item.get("created_at", "")))
        updated["cursor_value"] = str(last.get("created_at", last.get("id", "")))
    elif cursor_type in {"after_id", "after_message_id"}:
        updated["cursor_value"] = _max_message_id(messages)
    else:
        updated["cursor_value"] = _max_message_id(messages)
    updated["last_poll_at"] = datetime.now(timezone.utc).isoformat()
    return updated


def _pipeline_error_category(exc: BaseException) -> str:
    if isinstance(exc, ValueError):
        return "validation_error"
    if isinstance(exc, TimeoutError):
        return "pipeline_timeout"
    if isinstance(exc, urllib.error.URLError):
        return "pipeline_network_error"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_pipeline_json"
    return type(exc).__name__


def process_messages(
    messages: list[dict[str, Any]],
    *,
    pipeline_fn: PipelineFn | None = None,
    room_fetch_fn: RoomFetchFn | None = None,
) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    seller_count = 0
    duplicate_count = 0
    error_count = 0
    non_shop_count = 0
    timeline_sync_count = 0
    pipeline_call_count = 0
    fetcher = room_fetch_fn or fetch_room

    ordered_messages = sorted(
        [message for message in messages if message.get("id") is not None],
        key=lambda message: _message_id_sort_key(message["id"]),
    )

    for message in ordered_messages:
        sender = str(message.get("sender", ""))
        message_id = message.get("id")
        room_id = message.get("room_id")

        if room_id is not None:
            room = fetcher(room_id)
            if room is not None:
                timeline_sync_count += update_room_timeline_for_existing_records(
                    room_id,
                    room,
                    room_last_message_id=message_id,
                )

        if sender != _SHOP_SENDER:
            non_shop_count += 1
            continue

        seller_count += 1
        if message_id is None:
            error_count += 1
            _log("process error: missing_message_id")
            continue
        if exists_message(str(message_id)):
            duplicate_count += 1
            continue

        (
            pipeline_request,
            conversation_context,
            timeline_messages,
            hydration_warnings,
        ) = _prepare_hydrated_processing(message, room_fetch_fn=room_fetch_fn)

        try:
            pipeline_response = call_pipeline(pipeline_request, pipeline_fn=pipeline_fn)
            pipeline_call_count += 1
        except (ValueError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            error_count += 1
            _log(f"process error: {_pipeline_error_category(exc)}")
            record = {
                "record_id": f"{message.get('room_id')}:{message_id}",
                "target_message_id": str(message_id),
                "room_id": str(message.get("room_id", "")),
                "shop_id": str(message.get("shop_id", "")),
                "room_type": str(message.get("room_type", "")),
                "status": "error",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_at_jalali": to_jalali(),
                "seller_message": str(message.get("content", "")),
                "conversation_context": conversation_context,
                "timeline_messages": timeline_messages,
                "pipeline": {},
                "tool_output": [],
                "warnings": ["pipeline_error", *hydration_warnings],
                "feedback": None,
                "send_log": [],
            }
            append_record(record)
            created.append(record)
            continue

        record = build_review_record(
            message,
            pipeline_response,
            conversation_context,
            timeline_messages=timeline_messages,
            record_warnings=hydration_warnings,
        )
        append_record(record)
        created.append(record)

    return {
        "created": created,
        "seller_count": seller_count,
        "duplicate_count": duplicate_count,
        "error_count": error_count,
        "non_shop_count": non_shop_count,
        "ignored_sender_count": non_shop_count,
        "timeline_sync_count": timeline_sync_count,
        "pipeline_call_count": pipeline_call_count,
        "processed_count": len(created),
    }


def _print_startup(interval_seconds: int) -> None:
    poller_state = load_poller_state()
    _log("HITL poller starting")
    _log(f"poll interval: {interval_seconds}s")
    _log(f"state path: {state_dir()}")
    _log(f"hitl state file: {hitl_state_path()}")
    _log(f"poller state file: {poller_state_path()}")
    _log(f"cursor_type: {poller_state.get('cursor_type', 'after_message_id')}")
    _log(f"cursor_value: {poller_state.get('cursor_value')}")


def _print_poll_summary(summary: dict[str, Any]) -> None:
    if summary.get("skipped"):
        _log(f"poll skipped: {summary.get('reason', 'unknown')}")
        return

    _log("poll started")
    _log(f"fetched message count: {summary.get('fetched', 0)}")
    _log(f"cursor_value: {summary.get('cursor_before')}")
    _log(f"client-side new message count: {summary.get('client_side_new_count', 0)}")
    _log(f"filtered old message count: {summary.get('filtered_old_count', 0)}")
    _log(f"seller message count: {summary.get('seller_count', 0)}")
    _log(f"ignored sender count: {summary.get('ignored_sender_count', 0)}")
    _log(f"timeline sync count: {summary.get('timeline_sync_count', 0)}")
    _log(f"skipped duplicate count: {summary.get('duplicate_count', 0)}")
    _log(f"processed count: {summary.get('processed_count', 0)}")
    _log(f"error count: {summary.get('error_count', 0)}")
    _log(f"created record count: {summary.get('created', 0)}")
    _log(f"cursor before: {summary.get('cursor_before')}")
    _log(f"new cursor_value: {summary.get('cursor_value')}")


def run_poll_once(
    *,
    fetch_fn: FetchFn | None = None,
    pipeline_fn: PipelineFn | None = None,
    room_fetch_fn: RoomFetchFn | None = None,
) -> dict[str, Any]:
    if poller_lock_exists():
        return {"skipped": True, "reason": "lock_exists"}

    if not acquire_poller_lock():
        return {"skipped": True, "reason": "lock_exists"}

    try:
        poller_state = load_poller_state()
        cursor_before = poller_state.get("cursor_value")
        raw_messages = _fetch_messages_raw(poller_state, fetch_fn=fetch_fn)
        messages_to_process, client_side_new_count, filtered_old_count = (
            _log_client_side_cursor_filter(raw_messages, cursor_before)
        )
        result = process_messages(
            messages_to_process,
            pipeline_fn=pipeline_fn,
            room_fetch_fn=room_fetch_fn,
        )
        updated_state = _update_cursor(poller_state, raw_messages)
        save_poller_state(updated_state)
        return {
            "skipped": False,
            "fetched": len(raw_messages),
            "client_side_new_count": client_side_new_count,
            "filtered_old_count": filtered_old_count,
            "created": len(result["created"]),
            "seller_count": result["seller_count"],
            "duplicate_count": result["duplicate_count"],
            "error_count": result["error_count"],
            "ignored_sender_count": result["ignored_sender_count"],
            "timeline_sync_count": result["timeline_sync_count"],
            "pipeline_call_count": result["pipeline_call_count"],
            "processed_count": result["processed_count"],
            "cursor_before": cursor_before,
            "cursor_value": updated_state.get("cursor_value"),
        }
    finally:
        release_poller_lock()


def run_poller_loop(
    interval_seconds: int = 10,
    *,
    fetch_fn: FetchFn | None = None,
    pipeline_fn: PipelineFn | None = None,
) -> None:
    while True:
        summary = run_poll_once(fetch_fn=fetch_fn, pipeline_fn=pipeline_fn)
        _print_poll_summary(summary)
        time.sleep(interval_seconds)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HITL message poller")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one poll cycle and exit",
    )
    parser.add_argument(
        "--from-file",
        dest="from_file",
        default=None,
        help="Load latest shop message from room JSONL for local testing",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    interval = int(os.getenv("HITL_POLL_INTERVAL_SECONDS", "10"))
    _print_startup(interval)

    fetch_fn: FetchFn | None = None
    if args.from_file:
        loaded = load_messages_from_file(args.from_file)
        fetch_fn = lambda _state: loaded
        _log(f"from-file loaded message count: {len(loaded)}")

    if args.once:
        summary = run_poll_once(fetch_fn=fetch_fn)
        _print_poll_summary(summary)
        return 0

    run_poller_loop(interval, fetch_fn=fetch_fn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
