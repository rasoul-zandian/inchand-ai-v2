"""Inchand order lookup tool adapter."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from app.config import settings
from app.models.tool_contracts import ToolRequest, ToolResult

ORDER_LOOKUP_TOOL = "order_lookup"

FetchFn = Callable[[str, str | None, float], tuple[int, dict]]


def _normalize_order_id(order_id: str) -> str:
    cleaned = order_id.strip()
    match = re.match(r"^INC[\s-]*(\d+)$", cleaned, re.IGNORECASE)
    if match:
        return f"INC-{match.group(1)}"
    if cleaned.isdigit():
        return f"INC-{cleaned}"
    return cleaned


def _request_url_base(order_id: str, shop_id: str | None) -> str:
    base = settings.inchand_api_base_url.rstrip("/") if settings.inchand_api_base_url else ""
    path = f"/orders/{urllib.parse.quote(order_id)}"
    if shop_id:
        return f"{base}{path}?{urllib.parse.urlencode({'shop_id': shop_id})}"
    return f"{base}{path}"


def _response_shape_summary(payload: object) -> str:
    if isinstance(payload, dict):
        keys = sorted(str(key) for key in payload.keys())
        if "data" in payload and isinstance(payload["data"], dict):
            inner = sorted(str(key) for key in payload["data"].keys())
            return f"dict:data[{','.join(inner[:8])}]"
        return f"dict:{','.join(keys[:8])}"
    return type(payload).__name__


def _failure_result(
    *,
    error: str,
    order_id: str | None = None,
    http_status: int | None = None,
    request_url_base: str | None = None,
    response_shape_summary: str | None = None,
    parse_error: str | None = None,
) -> ToolResult:
    data: dict[str, str] = {}
    if order_id:
        data["normalized_order_id"] = order_id
    if http_status is not None:
        data["http_status"] = str(http_status)
    if request_url_base:
        data["request_url_base"] = request_url_base
    if response_shape_summary:
        data["response_shape_summary"] = response_shape_summary
    if parse_error:
        data["parse_error"] = parse_error
    return ToolResult(
        tool_name=ORDER_LOOKUP_TOOL,
        success=False,
        data=data,
        summary="",
        error=error,
    )


def _first_order_id_value(entities: dict[str, str | list[str]]) -> str | None:
    order_id = entities.get("order_id")
    if isinstance(order_id, str) and order_id.strip():
        return order_id.strip()

    order_ids = entities.get("order_ids")
    if isinstance(order_ids, list):
        for value in order_ids:
            if isinstance(value, str) and value.strip():
                return value.strip()
    elif isinstance(order_ids, str) and order_ids.strip():
        return order_ids.split(",")[0].strip()

    return None


def _extract_order_id(entities: dict[str, str | list[str]]) -> str | None:
    order_id = _first_order_id_value(entities)
    if order_id:
        return _normalize_order_id(order_id)
    return None


def _extract_shop_id(request: ToolRequest) -> str | None:
    shop_id = request.entities.get("shop_id") or request.context.get("shop_id")
    if shop_id and shop_id.strip():
        return shop_id.strip()
    return None


def _unwrap_payload(payload: dict) -> dict:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def _providers_summary(providers: list[dict]) -> str:
    parts: list[str] = []
    for item in providers[:3]:
        provider_id = str(item.get("id", ""))
        status = str(item.get("status", ""))
        if provider_id or status:
            parts.append(f"{provider_id}:{status}".strip(":"))
    return ";".join(parts)


def _parcel_status_name(parcel: dict) -> str:
    status_name = parcel.get("status_name")
    if status_name:
        return str(status_name)
    status_detail = parcel.get("status_detail")
    if isinstance(status_detail, dict) and status_detail.get("name"):
        return str(status_detail["name"])
    return ""


def _provider_shop_id(provider: dict) -> str:
    for key in ("shop_id", "shopId"):
        value = provider.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _select_primary_provider(
    providers: list[dict],
    shop_id: str | None,
) -> tuple[dict, bool, bool]:
    if not providers:
        return {}, False, True

    if not shop_id:
        primary = providers[0] if isinstance(providers[0], dict) else {}
        return primary, False, True

    for provider in providers:
        if isinstance(provider, dict) and _provider_shop_id(provider) == shop_id:
            return provider, True, True

    return {}, False, False


def _map_safe_order_data(
    order_id: str,
    payload: dict,
    shop_id: str | None = None,
) -> dict[str, str]:
    body = _unwrap_payload(payload)
    providers = body.get("providers") or []
    if not isinstance(providers, list):
        providers = []

    provider_dicts = [provider for provider in providers if isinstance(provider, dict)]
    primary, is_shop_scoped, shop_provider_match = _select_primary_provider(
        provider_dicts,
        shop_id,
    )

    parcel = primary.get("parcel") or {}
    if not isinstance(parcel, dict):
        parcel = {}

    tracking_code = ""
    if primary:
        tracking_code = str(
            parcel.get("tracking_code") or body.get("tracking_code") or ""
        )
    is_delivered = body.get("is_delivered_in_inchand", body.get("is_delivered", False))

    data = {
        "order_id": order_id,
        "found": "true",
        "normalized_order_id": order_id,
        "order_status": str(body.get("order_status", body.get("status", ""))),
        "payment_status": str(body.get("payment_status", "")),
        "provider_count": str(len(provider_dicts)),
        "primary_provider_shop_id": _provider_shop_id(primary),
        "primary_provider_status": str(primary.get("status", "")),
        "primary_parcel_status_name": _parcel_status_name(parcel),
        "primary_parcel_tracking_code": tracking_code,
        "has_parcel_tracking_code": "true" if tracking_code else "false",
        "is_delivered_in_inchand": str(bool(is_delivered)).lower(),
        "is_shop_scoped": "true" if is_shop_scoped else "false",
        "providers_summary": _providers_summary(provider_dicts),
        "response_shape_summary": _response_shape_summary(payload),
    }

    if shop_id:
        data["shop_provider_match"] = "true" if shop_provider_match else "false"
        if not shop_provider_match:
            data["provider_not_found_for_shop"] = "true"

    return data


def _build_summary(data: dict[str, str]) -> str:
    if data.get("found") != "true":
        return f"Order {data.get('order_id', '')} was not found."
    return (
        f"Order {data['order_id']} status is {data.get('order_status', 'unknown')} "
        f"with payment status {data.get('payment_status', 'unknown')}."
    )


def _default_fetch_order(order_id: str, shop_id: str | None, timeout: float) -> tuple[int, dict]:
    if not settings.inchand_api_base_url or not settings.inchand_api_key_value:
        raise RuntimeError("missing_api_config")

    url = _request_url_base(order_id, shop_id)
    request = urllib.request.Request(
        url,
        headers={settings.inchand_api_key_name: settings.inchand_api_key_value},
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code = response.status
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        raw = exc.read().decode("utf-8", errors="replace")

    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid_json:{exc.msg}") from exc

    if not isinstance(body, dict):
        raise ValueError("invalid_response")
    return status_code, body


def run_order_lookup(
    request: ToolRequest,
    *,
    fetch_fn: FetchFn | None = None,
) -> ToolResult:
    if request.tool_name != ORDER_LOOKUP_TOOL:
        return _failure_result(error="invalid_tool_name")

    order_id = _extract_order_id(request.entities)
    if not order_id:
        return _failure_result(error="missing_order_id")

    shop_id = _extract_shop_id(request)
    timeout = settings.inchand_order_lookup_timeout_seconds
    caller = fetch_fn or _default_fetch_order
    request_url_base = _request_url_base(order_id, shop_id)

    try:
        status_code, payload = caller(order_id, shop_id, timeout)
    except RuntimeError:
        return _failure_result(
            error="missing_config",
            order_id=order_id,
            request_url_base=settings.inchand_api_base_url.rstrip("/")
            if settings.inchand_api_base_url
            else "",
        )
    except TimeoutError:
        return _failure_result(
            error="order_lookup_failed",
            order_id=order_id,
            request_url_base=request_url_base,
            parse_error="timeout",
        )
    except urllib.error.URLError:
        return _failure_result(
            error="order_lookup_failed",
            order_id=order_id,
            request_url_base=request_url_base,
            parse_error="network_error",
        )
    except ValueError as exc:
        return _failure_result(
            error="parse_error",
            order_id=order_id,
            request_url_base=request_url_base,
            parse_error=str(exc),
        )

    shape = _response_shape_summary(payload)

    if status_code in {401, 403}:
        return _failure_result(
            error="auth_error",
            order_id=order_id,
            http_status=status_code,
            request_url_base=request_url_base,
            response_shape_summary=shape,
        )

    if status_code == 404:
        data = {
            "order_id": order_id,
            "found": "false",
            "normalized_order_id": order_id,
            "http_status": str(status_code),
            "request_url_base": request_url_base,
            "response_shape_summary": shape,
        }
        return ToolResult(
            tool_name=ORDER_LOOKUP_TOOL,
            success=True,
            data=data,
            summary=_build_summary(data),
        )

    if status_code >= 400:
        return _failure_result(
            error="order_lookup_failed",
            order_id=order_id,
            http_status=status_code,
            request_url_base=request_url_base,
            response_shape_summary=shape,
        )

    try:
        data = _map_safe_order_data(order_id, payload, shop_id=shop_id)
    except (TypeError, AttributeError) as exc:
        return _failure_result(
            error="parse_error",
            order_id=order_id,
            http_status=status_code,
            request_url_base=request_url_base,
            response_shape_summary=shape,
            parse_error=str(exc),
        )

    data["http_status"] = str(status_code)
    data["request_url_base"] = request_url_base

    return ToolResult(
        tool_name=ORDER_LOOKUP_TOOL,
        success=True,
        data=data,
        summary=_build_summary(data),
    )
