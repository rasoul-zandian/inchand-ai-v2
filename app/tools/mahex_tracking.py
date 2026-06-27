"""Mahex parcel tracking via public API."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Callable

from app.models.tool_contracts import ToolRequest, ToolResult

MAHEX_TRACKING_TOOL = "mahex_tracking"
MAHEX_API_BASE = "https://mahex.com/website/api/web/v1/tr"
TIMEOUT_SECONDS = 10

FetchFn = Callable[[str], tuple[int, dict | None, str | None]]


def _tracking_digits(value: str) -> str:
    text = value.strip()
    persian = "۰۱۲۳۴۵۶۷۸۹"
    for index, digit in enumerate(persian):
        text = text.replace(digit, str(index))
    return re.sub(r"\D", "", text)


def is_mahex_tracking_code(tracking_code: str) -> bool:
    return len(_tracking_digits(tracking_code)) == 14


def is_iran_post_tracking_code(tracking_code: str) -> bool:
    length = len(_tracking_digits(tracking_code))
    return 20 <= length <= 26


def _extract_tracking_code(entities: dict[str, str | list[str]]) -> str | None:
    tracking_code = entities.get("tracking_code")
    if isinstance(tracking_code, str) and tracking_code.strip():
        return tracking_code.strip()
    return None


def _is_delivered(payload: dict) -> bool:
    current_states = payload.get("currentStates")
    if isinstance(current_states, list):
        for item in current_states:
            if not isinstance(item, dict):
                continue
            status_code = str(item.get("statusCode", "")).upper()
            if status_code == "DELIVERED":
                return True
            status_name = str(item.get("statusName", ""))
            if "تحویل" in status_name:
                return True
    current_state_name = str(payload.get("currentStateName", ""))
    return "تحویل" in current_state_name


def _status_text(payload: dict) -> str:
    current_states = payload.get("currentStates")
    if isinstance(current_states, list) and current_states:
        first = current_states[0]
        if isinstance(first, dict):
            status_name = str(first.get("statusName", "")).strip()
            if status_name:
                return status_name
    return str(payload.get("currentStateName", "")).strip()


def _last_update(payload: dict) -> str:
    current_states = payload.get("currentStates")
    if isinstance(current_states, list) and current_states:
        first = current_states[0]
        if isinstance(first, dict):
            action_datetime = str(first.get("actionDatetime", "")).strip()
            if action_datetime:
                return action_datetime
    return str(payload.get("actualDeliveryDate", "")).strip()


def _failure_result(
    *,
    tracking_code: str,
    error: str,
    http_status: int | None = None,
) -> ToolResult:
    data = {
        "tracking_code": tracking_code,
        "carrier": "mahex",
        "found": "false",
    }
    if http_status is not None:
        data["http_status"] = str(http_status)
    return ToolResult(
        tool_name=MAHEX_TRACKING_TOOL,
        success=False,
        data=data,
        summary="",
        error=error,
    )


def _success_result(tracking_code: str, payload: dict, http_status: int) -> ToolResult:
    status_text = _status_text(payload)
    delivered = _is_delivered(payload)
    last_update = _last_update(payload)
    data = {
        "tracking_code": tracking_code,
        "carrier": "mahex",
        "found": "true",
        "current_state_name": str(payload.get("currentStateName", "")).strip(),
        "status_text": status_text,
        "delivered": "true" if delivered else "false",
        "http_status": str(http_status),
    }
    if last_update:
        data["last_update"] = last_update
    summary = status_text or data["current_state_name"]
    return ToolResult(
        tool_name=MAHEX_TRACKING_TOOL,
        success=True,
        data=data,
        summary=summary,
        error=None,
    )


def _default_fetch(tracking_code: str) -> tuple[int, dict | None, str | None]:
    url = f"{MAHEX_API_BASE}/{urllib.request.quote(tracking_code, safe='')}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                return response.status, None, "invalid_json"
            if not isinstance(payload, dict):
                return response.status, None, "invalid_response_shape"
            return response.status, payload, None
    except TimeoutError:
        return 0, None, "timeout"
    except urllib.error.HTTPError as exc:
        return exc.code, None, "http_error"
    except urllib.error.URLError:
        return 0, None, "network_error"


def run_mahex_tracking(
    request: ToolRequest,
    *,
    fetch_fn: FetchFn | None = None,
) -> ToolResult:
    tracking_code = _extract_tracking_code(request.entities)
    if not tracking_code:
        return _failure_result(tracking_code="", error="missing_tracking_code")

    normalized = _tracking_digits(tracking_code)
    if not normalized:
        return _failure_result(tracking_code=tracking_code, error="invalid_tracking_code")

    caller = fetch_fn or _default_fetch
    http_status, payload, fetch_error = caller(normalized)

    if fetch_error == "timeout":
        return _failure_result(
            tracking_code=normalized,
            error="mahex_tracking_timeout",
            http_status=http_status or None,
        )
    if fetch_error in {"network_error", "invalid_json", "invalid_response_shape"}:
        return _failure_result(
            tracking_code=normalized,
            error=f"mahex_tracking_{fetch_error}",
            http_status=http_status or None,
        )
    if fetch_error == "http_error" or http_status >= 400 or payload is None:
        return _failure_result(
            tracking_code=normalized,
            error="mahex_tracking_not_found",
            http_status=http_status or None,
        )

    consignment_id = str(payload.get("consignmentId", "")).strip()
    if not consignment_id:
        return _failure_result(
            tracking_code=normalized,
            error="mahex_tracking_not_found",
            http_status=http_status,
        )

    return _success_result(normalized, payload, http_status)


def run_selected_mahex_tracking(
    tool_selection_result,
    intent_result,
    *,
    tracking_fn: Callable[[ToolRequest], ToolResult] | None = None,
) -> ToolResult | None:
    if MAHEX_TRACKING_TOOL not in tool_selection_result.selected_tools:
        return None

    requests = tool_selection_result.to_requests(
        intent=intent_result.primary_intent.value,
        entities=intent_result.entities,
    )
    mahex_request = next(
        (item for item in requests if item.tool_name == MAHEX_TRACKING_TOOL),
        None,
    )
    if mahex_request is None:
        return None

    caller = tracking_fn or run_mahex_tracking
    return caller(mahex_request)
