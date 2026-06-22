"""Poll Inchand seller messages and enqueue HITL review records."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

from app.integrations.inchand_poller_adapter import build_pipeline_request_from_inchand_message

from hitl.jalali import to_jalali
from hitl.state import (
    acquire_poller_lock,
    append_record,
    exists_message,
    load_poller_state,
    poller_lock_exists,
    release_poller_lock,
    save_poller_state,
)

FetchFn = Callable[[dict[str, Any]], list[dict[str, Any]]]
PipelineFn = Callable[[dict[str, Any]], dict[str, Any]]

_SHOP_SENDER = "shop"
_IGNORED_SENDERS = {"admin", "system"}


def _messages_url() -> str:
    base = os.getenv("INCHAND_API_BASE_URL", "").rstrip("/")
    path = os.getenv(
        "HITL_INCHAND_MESSAGES_PATH",
        "/api/v1/internal/messages",
    )
    return f"{base}{path}"


def _pipeline_url() -> str:
    return os.getenv(
        "HITL_PIPELINE_URL",
        "http://127.0.0.1:8000/internal/pipeline/run",
    )


def _auth_token() -> str:
    return os.getenv("INCHAND_INTERNAL_TOKEN") or os.getenv("INCHAND_API_KEY_VALUE", "")


def _cursor_query(cursor_type: str, cursor_value: str | None) -> dict[str, str]:
    if not cursor_value:
        return {}
    if cursor_type == "after_id":
        return {"after_id": cursor_value}
    if cursor_type == "after_timestamp":
        return {"after_timestamp": cursor_value}
    return {"after_message_id": cursor_value}


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

    token = _auth_token()
    base_url = _messages_url()
    if not token or not base_url.startswith("http"):
        return []

    params = {"limit": str(limit), **_cursor_query(cursor_type, cursor_value)}
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={"Authorization": token},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError):
        return []

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data", payload.get("messages", []))
        if isinstance(data, list):
            return data
    return []


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
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("invalid_pipeline_response")
    return parsed


def build_review_record(
    message: dict[str, Any],
    pipeline_response: dict[str, Any],
    conversation_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    message_id = str(message["id"])
    room_id = str(message["room_id"])
    now = datetime.now(timezone.utc)
    record_id = f"{room_id}:{message_id}"
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
        "conversation_context": _last_context_messages(conversation_context),
        "pipeline": pipeline_response,
        "tool_output": pipeline_response.get("safe_tool_output", []),
        "warnings": list(pipeline_response.get("warnings", [])),
        "feedback": None,
        "send_log": [],
    }


def _update_cursor(
    poller_state: dict[str, Any],
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    if not messages:
        return poller_state

    cursor_type = str(poller_state.get("cursor_type", "after_message_id"))
    last = messages[-1]
    updated = dict(poller_state)
    if cursor_type == "after_timestamp":
        updated["cursor_value"] = str(last.get("created_at", last.get("id", "")))
    elif cursor_type == "after_id":
        updated["cursor_value"] = str(last.get("id", ""))
    else:
        updated["cursor_value"] = str(last.get("id", ""))
    updated["last_poll_at"] = datetime.now(timezone.utc).isoformat()
    return updated


def process_messages(
    messages: list[dict[str, Any]],
    *,
    pipeline_fn: PipelineFn | None = None,
) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    for message in messages:
        sender = str(message.get("sender", ""))
        if sender != _SHOP_SENDER:
            continue
        message_id = message.get("id")
        if message_id is None:
            continue
        if exists_message(str(message_id)):
            continue

        context = message.get("conversation_context")
        if not isinstance(context, list):
            context = message.get("context")
        if not isinstance(context, list):
            context = None

        try:
            pipeline_request = build_pipeline_request_from_inchand_message(
                message,
                conversation_context=context,
            )
            pipeline_response = call_pipeline(pipeline_request, pipeline_fn=pipeline_fn)
        except (ValueError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
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
                "conversation_context": _last_context_messages(context),
                "pipeline": {},
                "tool_output": [],
                "warnings": ["pipeline_error"],
                "feedback": None,
                "send_log": [],
            }
            append_record(record)
            created.append(record)
            continue

        record = build_review_record(message, pipeline_response, context)
        append_record(record)
        created.append(record)
    return created


def run_poll_once(
    *,
    fetch_fn: FetchFn | None = None,
    pipeline_fn: PipelineFn | None = None,
) -> dict[str, Any]:
    if poller_lock_exists():
        return {"skipped": True, "reason": "lock_exists"}

    if not acquire_poller_lock():
        return {"skipped": True, "reason": "lock_exists"}

    try:
        poller_state = load_poller_state()
        messages = fetch_new_messages(poller_state, fetch_fn=fetch_fn)
        created = process_messages(messages, pipeline_fn=pipeline_fn)
        save_poller_state(_update_cursor(poller_state, messages))
        return {
            "skipped": False,
            "fetched": len(messages),
            "created": len(created),
        }
    finally:
        release_poller_lock()


def run_poller_loop(interval_seconds: int = 10) -> None:
    while True:
        run_poll_once()
        time.sleep(interval_seconds)


def main() -> int:
    interval = int(os.getenv("HITL_POLL_INTERVAL_SECONDS", "10"))
    run_poller_loop(interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
