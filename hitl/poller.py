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

from app.integrations.inchand_poller_adapter import build_pipeline_request_from_inchand_message

import app.config  # noqa: F401 — load .env for poller CLI

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

_SHOP_SENDER = "shop"


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


def _auth_token() -> str:
    return os.getenv("INCHAND_INTERNAL_TOKEN") or os.getenv("INCHAND_API_KEY_VALUE", "")


def _fetch_configured() -> bool:
    base = os.getenv("INCHAND_API_BASE_URL", "")
    return bool(_auth_token() and base.startswith("http"))


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
        headers={"Authorization": _auth_token()},
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
) -> dict[str, Any]:
    if poller_lock_exists():
        return {"skipped": True, "reason": "lock_exists"}

    if not acquire_poller_lock():
        return {"skipped": True, "reason": "lock_exists"}

    try:
        poller_state = load_poller_state()
        cursor_before = poller_state.get("cursor_value")
        messages = fetch_new_messages(poller_state, fetch_fn=fetch_fn)
        result = process_messages(messages, pipeline_fn=pipeline_fn)
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
