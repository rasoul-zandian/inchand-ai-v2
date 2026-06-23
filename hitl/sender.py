"""Send approved replies into Inchand."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from app.config import settings

SEND_TIMEOUT_SECONDS = 10.0

RequestFn = Callable[..., tuple[int, dict[str, Any]]]


def _log(message: str) -> None:
    print(message, flush=True)


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    safe: dict[str, str] = {}
    auth_name = settings.inchand_api_key_name
    for key, value in headers.items():
        if key == auth_name or key.lower() in {"authorization", "x-api-key"}:
            safe[key] = "***"
        else:
            safe[key] = value
    return safe


def _log_send_request(
    *,
    url: str,
    method: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> None:
    _log("SEND REQUEST")
    _log(f"URL: {url}")
    _log(f"METHOD: {method}")
    _log("HEADERS:")
    _log(json.dumps(_safe_headers(headers), ensure_ascii=False, indent=2))
    _log("PAYLOAD:")
    _log(json.dumps(payload, ensure_ascii=False, indent=2))


def _log_send_response(*, status: int, body: str) -> None:
    _log("RESPONSE:")
    _log(f"status={status}")
    _log(f"body={body}")


def parse_refer_to(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    if not text.isdigit():
        raise ValueError("invalid_refer_to")
    return int(text)


def _create_message_endpoint() -> str:
    explicit = os.getenv("HITL_INCHAND_CREATE_MESSAGE_PATH")
    if explicit:
        return explicit
    base = os.getenv("INCHAND_API_BASE_URL", "").rstrip("/")
    if base.endswith("/api/v1/internal"):
        return "/message/create"
    return "/api/v1/internal/message/create"


def _create_message_url() -> str:
    base = os.getenv("INCHAND_API_BASE_URL", "").rstrip("/")
    path = _create_message_endpoint()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


_create_message_url_logged = False


def _log_create_message_url_once() -> None:
    global _create_message_url_logged
    if _create_message_url_logged:
        return
    _log(f"Create Message URL:\n{_create_message_url()}")
    _create_message_url_logged = True


def build_suggestion_content(record: dict[str, Any]) -> str:
    pipeline = record.get("pipeline", {})
    entities = pipeline.get("entities", {})
    entity_bits = []
    for key in ("order_id", "order_ids", "tracking_code", "iban", "card_number", "mobile_number"):
        value = entities.get(key)
        if value:
            entity_bits.append(f"{key}={value}")
    entity_text = ", ".join(entity_bits) if entity_bits else "none"
    return (
        f"AI intent={pipeline.get('primary_intent', '')} "
        f"confidence={pipeline.get('confidence', '')} "
        f"action={pipeline.get('suggested_action', '')} "
        f"source={pipeline.get('final_reply_source', '')} "
        f"entities={entity_text}"
    )


def _default_request(
    payload: dict[str, Any],
    *,
    timeout: float = SEND_TIMEOUT_SECONDS,
) -> tuple[int, dict[str, Any]]:
    if not settings.inchand_api_key_value:
        raise RuntimeError("missing_token")

    _log_create_message_url_once()
    url = _create_message_url()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        settings.inchand_api_key_name: settings.inchand_api_key_value,
        "Content-Type": "application/json",
    }
    _log_send_request(url=url, method="POST", headers=headers, payload=payload)
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode("utf-8", errors="replace")
    except TimeoutError as exc:
        raise TimeoutError("timeout") from exc

    _log_send_response(status=status, body=raw)

    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return status, parsed


def _send_message(
    *,
    record: dict[str, Any],
    message_type: int,
    content: str,
    meta: dict[str, Any],
    refer_to: int | None,
    request_fn: RequestFn | None = None,
    timeout: float = SEND_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    pipeline = record.get("pipeline", {})
    payload: dict[str, Any] = {
        "room_id": record.get("room_id"),
        "type": message_type,
        "content": content,
        "meta": meta,
    }
    if refer_to is not None:
        payload["refer_to"] = refer_to

    caller = request_fn or _default_request
    try:
        status, response = caller(payload, timeout=timeout)
    except RuntimeError:
        return {
            "success": False,
            "error": "missing_token",
            "message_type": message_type,
        }
    except TimeoutError:
        return {
            "success": False,
            "error": "timeout",
            "message_type": message_type,
        }
    except urllib.error.URLError:
        return {
            "success": False,
            "error": "network_error",
            "message_type": message_type,
        }

    success = 200 <= status < 300
    return {
        "success": success,
        "http_status": status,
        "message_type": message_type,
        "error": None if success else "api_failure",
        "response_id": response.get("id"),
    }


def send_reply(
    record: dict[str, Any],
    refer_to: int | None = None,
    *,
    request_fn: RequestFn | None = None,
    timeout: float = SEND_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    pipeline = record.get("pipeline", {})
    meta = {
        "ai_generated": True,
        "record_id": record.get("record_id"),
        "intent": pipeline.get("primary_intent"),
        "confidence": pipeline.get("confidence"),
    }
    return _send_message(
        record=record,
        message_type=1,
        content=str(pipeline.get("final_reply", "")),
        meta=meta,
        refer_to=refer_to,
        request_fn=request_fn,
        timeout=timeout,
    )


def send_suggestion(
    record: dict[str, Any],
    refer_to: int | None = None,
    *,
    request_fn: RequestFn | None = None,
    timeout: float = SEND_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    pipeline = record.get("pipeline", {})
    meta = {
        "ai_generated": True,
        "intent": pipeline.get("primary_intent"),
        "confidence": pipeline.get("confidence"),
        "entities": pipeline.get("entities", {}),
        "suggested_action": pipeline.get("suggested_action"),
        "final_reply_source": pipeline.get("final_reply_source"),
    }
    return _send_message(
        record=record,
        message_type=3,
        content=build_suggestion_content(record),
        meta=meta,
        refer_to=refer_to,
        request_fn=request_fn,
        timeout=timeout,
    )


def send_both(
    record: dict[str, Any],
    refer_to: int | None = None,
    *,
    request_fn: RequestFn | None = None,
    timeout: float = SEND_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    reply_result = send_reply(
        record,
        refer_to=refer_to,
        request_fn=request_fn,
        timeout=timeout,
    )
    suggestion_result = send_suggestion(
        record,
        refer_to=refer_to,
        request_fn=request_fn,
        timeout=timeout,
    )
    return [reply_result, suggestion_result]
