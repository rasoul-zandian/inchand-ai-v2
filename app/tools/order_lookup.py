"""Inchand order lookup tool adapter."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from app.config import settings
from app.models.tool_contracts import ToolRequest, ToolResult

ORDER_LOOKUP_TOOL = "order_lookup"

FetchFn = Callable[[str, str | None, float], tuple[int, dict]]


def _extract_order_id(entities: dict[str, str]) -> str | None:
    order_id = entities.get("order_id")
    if order_id and order_id.strip():
        return order_id.strip()

    order_ids = entities.get("order_ids")
    if order_ids:
        parts = [part.strip() for part in order_ids.split(",") if part.strip()]
        if parts:
            return parts[0]

    return None


def _extract_shop_id(request: ToolRequest) -> str | None:
    shop_id = request.entities.get("shop_id") or request.context.get("shop_id")
    if shop_id and shop_id.strip():
        return shop_id.strip()
    return None


def _providers_summary(providers: list[dict]) -> str:
    parts: list[str] = []
    for item in providers[:3]:
        provider_id = str(item.get("id", ""))
        status = str(item.get("status", ""))
        if provider_id or status:
            parts.append(f"{provider_id}:{status}".strip(":"))
    return ";".join(parts)


def _map_safe_order_data(order_id: str, payload: dict) -> dict[str, str]:
    providers = payload.get("providers") or []
    if not isinstance(providers, list):
        providers = []

    primary = providers[0] if providers else {}
    if not isinstance(primary, dict):
        primary = {}

    parcel = primary.get("parcel") or {}
    if not isinstance(parcel, dict):
        parcel = {}

    tracking_code = str(parcel.get("tracking_code") or "")
    is_delivered = payload.get("is_delivered_in_inchand", payload.get("is_delivered", False))

    return {
        "order_id": order_id,
        "found": "true",
        "order_status": str(payload.get("order_status", payload.get("status", ""))),
        "payment_status": str(payload.get("payment_status", "")),
        "provider_count": str(len(providers)),
        "primary_provider_status": str(primary.get("status", "")),
        "primary_parcel_status_name": str(parcel.get("status_name", "")),
        "primary_parcel_tracking_code": tracking_code,
        "has_parcel_tracking_code": "true" if tracking_code else "false",
        "is_delivered_in_inchand": str(bool(is_delivered)).lower(),
        "providers_summary": _providers_summary(providers),
    }


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

    base = settings.inchand_api_base_url.rstrip("/")
    query = urllib.parse.urlencode({"shop_id": shop_id}) if shop_id else ""
    url = f"{base}/orders/{urllib.parse.quote(order_id)}"
    if query:
        url = f"{url}?{query}"

    request = urllib.request.Request(
        url,
        headers={settings.inchand_api_key_name: settings.inchand_api_key_value},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict):
        raise ValueError("invalid_response")
    return response.status, body


def run_order_lookup(
    request: ToolRequest,
    *,
    fetch_fn: FetchFn | None = None,
) -> ToolResult:
    if request.tool_name != ORDER_LOOKUP_TOOL:
        return ToolResult(
            tool_name=ORDER_LOOKUP_TOOL,
            success=False,
            summary="",
            error="invalid_tool_name",
        )

    order_id = _extract_order_id(request.entities)
    if not order_id:
        return ToolResult(
            tool_name=ORDER_LOOKUP_TOOL,
            success=False,
            summary="",
            error="missing_order_id",
        )

    shop_id = _extract_shop_id(request)
    timeout = settings.inchand_order_lookup_timeout_seconds
    caller = fetch_fn or _default_fetch_order

    try:
        status_code, payload = caller(order_id, shop_id, timeout)
    except RuntimeError:
        return ToolResult(
            tool_name=ORDER_LOOKUP_TOOL,
            success=False,
            summary="",
            error="missing_api_config",
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return ToolResult(
            tool_name=ORDER_LOOKUP_TOOL,
            success=False,
            summary="",
            error="order_lookup_failed",
        )

    if status_code == 404:
        data = {"order_id": order_id, "found": "false"}
        return ToolResult(
            tool_name=ORDER_LOOKUP_TOOL,
            success=True,
            data=data,
            summary=_build_summary(data),
        )

    if status_code >= 400:
        return ToolResult(
            tool_name=ORDER_LOOKUP_TOOL,
            success=False,
            summary="",
            error="order_lookup_failed",
        )

    data = _map_safe_order_data(order_id, payload)
    return ToolResult(
        tool_name=ORDER_LOOKUP_TOOL,
        success=True,
        data=data,
        summary=_build_summary(data),
    )
