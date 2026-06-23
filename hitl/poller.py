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
    poller_lock_exists,
    poller_state_path,
    release_poller_lock,
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


def _log_fetch_error(category: str, detail: str = "") -> None:
    if detail:
        _log(f"fetch error: {category} ({detail})")
    else:
        _log(f"fetch error: {category}")


def fetch_new_messages(
    poller_state: dict[str, Any] | None = None,
    *,
    fetch_fn: FetchFn | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    state = poller_state or load_poller_state()
    cursor_type = str(state.get("cursor_type", "after_message_id"))
    cursor_value = state.get("cursor_value")

    if fetch_fn is not None:
        return fetch_fn(state)

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

    _log(f"fetched count: {len(messages)}")
    return messages


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


def _parse_room_response(
    payload: Any,
    room_id: str | int,
) -> tuple[dict[str, Any] | None, str]:
    room_id_text = str(room_id)

    if isinstance(payload, dict) and isinstance(payload.get("messages"), list):
        if payload.get("id") is None or str(payload.get("id")) == room_id_text:
            return payload, "room_object"

    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            if data.get("id") is None or str(data.get("id")) == room_id_text:
                return data, "data_object"
        if isinstance(data, list):
            for room in data:
                if isinstance(room, dict) and str(room.get("id")) == room_id_text:
                    return room, "data_list"
        rooms = payload.get("rooms")
        if isinstance(rooms, list):
            for room in rooms:
                if isinstance(room, dict) and str(room.get("id")) == room_id_text:
                    return room, "rooms_list"

    if isinstance(payload, list):
        for room in payload:
            if isinstance(room, dict) and str(room.get("id")) == room_id_text:
                return room, "list"

    return None, "unexpected_response_shape"


def fetch_room(room_id: str | int) -> dict[str, Any] | None:
    if not _fetch_configured():
        return None

    url = _rooms_url(room_id)
    path = urllib.parse.urlparse(url).path
    _log(f"fetch room path: {path}")
    _log(f"room_id: {room_id}")

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
    ignored_sender_count = 0

    for message in messages:
        sender = str(message.get("sender", ""))
        if sender != _SHOP_SENDER:
            ignored_sender_count += 1
            continue

        seller_count += 1
        message_id = message.get("id")
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
        "ignored_sender_count": ignored_sender_count,
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
    _log(f"seller message count: {summary.get('seller_count', 0)}")
    _log(f"ignored sender count: {summary.get('ignored_sender_count', 0)}")
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
        messages = fetch_new_messages(poller_state, fetch_fn=fetch_fn)
        result = process_messages(
            messages,
            pipeline_fn=pipeline_fn,
            room_fetch_fn=room_fetch_fn,
        )
        updated_state = _update_cursor(poller_state, messages)
        save_poller_state(updated_state)
        return {
            "skipped": False,
            "fetched": len(messages),
            "created": len(result["created"]),
            "seller_count": result["seller_count"],
            "duplicate_count": result["duplicate_count"],
            "error_count": result["error_count"],
            "ignored_sender_count": result["ignored_sender_count"],
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
