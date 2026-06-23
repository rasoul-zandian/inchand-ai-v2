"""Send approved replies into Inchand."""

from __future__ import annotations

import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from app.config import settings

SEND_TIMEOUT_SECONDS = 10.0

RequestFn = Callable[..., tuple[int, dict[str, Any]]]

_INTENT_LABELS_FA = {
    "complaint_order_followup": "پیگیری شکایت سفارش",
    "order_status_inquiry": "پیگیری وضعیت سفارش",
    "delivery_confirmation_request": "اعلام تحویل سفارش",
    "shipping_inquiry": "پیگیری ارسال / مرسوله",
    "bank_account_change": "تغییر اطلاعات بانکی",
    "settlement_inquiry": "پیگیری تسویه",
    "product_approval_request": "بررسی تایید محصول",
    "product_rejection_inquiry": "پیگیری رد محصول",
    "general_inquiry": "درخواست عمومی",
}

_ACTION_LABELS_FA = {
    "human_followup": "نیازمند بررسی کارشناس",
    "reply_to_seller": "قابل پاسخ به فروشنده",
    "request_missing_information": "نیاز به دریافت اطلاعات بیشتر",
    "escalate": "ارجاع فوری",
}

_TOOL_LABELS_FA = {
    "order_lookup": "جستجوی سفارش",
    "iran_post_tracking": "رهگیری پست",
    "product_lookup": "جستجوی محصول",
    "shop_lookup": "جستجوی فروشگاه",
}


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
    return build_admin_suggestion_content(record)


def _pipeline_field(record: dict[str, Any], key: str, default: Any = "") -> Any:
    return record.get("pipeline", {}).get(key, default)


def _format_confidence_percent(confidence: Any) -> str:
    if confidence is None or confidence == "":
        return "—"
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return str(confidence)
    if 0 <= value <= 1:
        return f"{round(value * 100)}%"
    return f"{round(value)}%"


def _persian_intent_label(intent: Any) -> str:
    text = str(intent or "").strip()
    if not text:
        return "—"
    return _INTENT_LABELS_FA.get(text, text.replace("_", " "))


def _persian_action_label(action: Any) -> str:
    text = str(action or "").strip()
    if not text:
        return "—"
    return _ACTION_LABELS_FA.get(text, text.replace("_", " "))


def _yes_no_persian(value: Any) -> str:
    if value is True:
        return "بله"
    if value is False:
        return "خیر"
    return "—"


def _record_warnings(record: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for source in (_pipeline_field(record, "warnings"), record.get("warnings")):
        if not isinstance(source, list):
            continue
        for item in source:
            text = str(item).strip()
            if text and text not in warnings:
                warnings.append(text)
    return warnings


def _record_tool_output(record: dict[str, Any]) -> list[dict[str, Any]]:
    output = record.get("tool_output")
    if isinstance(output, list):
        return [item for item in output if isinstance(item, dict)]
    safe_output = _pipeline_field(record, "safe_tool_output")
    if isinstance(safe_output, list):
        return [item for item in safe_output if isinstance(item, dict)]
    return []


def _truncate_text(text: str, limit: int = 220) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _tool_summary_lines(record: dict[str, Any]) -> list[str]:
    pipeline = record.get("pipeline", {})
    selected = [str(tool) for tool in (pipeline.get("selected_tools") or [])]
    tool_status = pipeline.get("tool_status")
    if not isinstance(tool_status, dict):
        tool_status = {}
    outputs = _record_tool_output(record)
    lines: list[str] = []

    for tool_name in selected:
        label = _TOOL_LABELS_FA.get(tool_name, tool_name.replace("_", " "))
        if tool_name == "order_lookup":
            if tool_status.get("order_lookup_success") is True or outputs:
                lines.append(f"✓ {label}")
            elif tool_status.get("order_lookup_executed"):
                lines.append(f"✗ {label}")
            else:
                lines.append(f"• {label}")
            continue
        if tool_name == "iran_post_tracking":
            tracking_lines = _tracking_summary_lines(outputs)
            if tracking_lines:
                lines.append(f"✓ {label}")
            else:
                lines.append(f"• {label}")
            continue
        lines.append(f"• {label}")
    return lines


def _order_summary_lines(outputs: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in outputs:
        order_id = str(item.get("order_id", "")).strip()
        if not order_id:
            continue
        lines.append(f"سفارش: {order_id}")
        order_status = str(item.get("order_status", "")).strip()
        if order_status:
            lines.append(f"وضعیت سفارش: {order_status}")
        parcel_status = str(item.get("parcel_status", "")).strip()
        if parcel_status:
            lines.append(f"وضعیت مرسوله: {parcel_status}")
        tracking_code = str(item.get("tracking_code", "")).strip()
        if tracking_code:
            lines.append(f"کد رهگیری: {tracking_code}")
    return lines


def _tracking_summary_lines(outputs: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in outputs:
        tracking_code = str(item.get("tracking_code", "")).strip()
        if not tracking_code:
            continue
        lines.append(f"کد رهگیری: {tracking_code}")
        parcel_status = str(item.get("parcel_status", "")).strip()
        if parcel_status:
            lines.append(f"وضعیت فعلی: {parcel_status}")
    return lines


def _recommended_next_action(record: dict[str, Any]) -> str:
    action = str(_pipeline_field(record, "suggested_action", "")).strip()
    needs_review = _pipeline_field(record, "needs_human_review")
    if needs_review is True or action == "human_followup":
        return "این مورد نیازمند بررسی کارشناس است؛ لطفاً پیش از ارسال پاسخ نهایی، جزئیات را تأیید کنید."
    if action == "reply_to_seller":
        return "پاسخ پیشنهادی AI قابل بررسی است؛ در صورت تأیید می‌توانید برای فروشنده ارسال کنید."
    if action == "request_missing_information":
        return "ابتدا اطلاعات تکمیلی از فروشنده دریافت شود و سپس پاسخ نهایی ثبت گردد."
    if action == "escalate":
        return "این مورد به ارجاع فوری نیاز دارد؛ لطفاً به تیم مربوطه منتقل کنید."
    return "لطفاً پیشنهاد AI را بررسی کرده و اقدام مناسب را انتخاب کنید."


def build_admin_suggestion_meta(record: dict[str, Any]) -> dict[str, Any]:
    pipeline = record.get("pipeline", {})
    return {
        "source": "inchand_ai_v2",
        "mode": "live_hitl",
        "message_kind": "ai_admin_suggestion",
        "record_id": record.get("record_id"),
        "room_id": record.get("room_id"),
        "target_message_id": record.get("target_message_id"),
        "primary_intent": pipeline.get("primary_intent"),
        "confidence": pipeline.get("confidence"),
        "suggested_action": pipeline.get("suggested_action"),
        "needs_human_review": pipeline.get("needs_human_review"),
        "should_send": pipeline.get("should_send"),
        "entities": pipeline.get("entities", {}),
        "selected_tools": list(pipeline.get("selected_tools") or []),
        "warnings": _record_warnings(record),
        "final_reply_source": pipeline.get("final_reply_source"),
    }


def build_admin_suggestion_content(record: dict[str, Any]) -> str:
    pipeline = record.get("pipeline", {})
    intent_label = _persian_intent_label(pipeline.get("primary_intent"))
    action_label = _persian_action_label(pipeline.get("suggested_action"))
    confidence = _format_confidence_percent(pipeline.get("confidence"))
    needs_review = _yes_no_persian(pipeline.get("needs_human_review"))
    seller_summary = html.escape(
        _truncate_text(str(record.get("seller_message", "") or "—"))
    )
    final_reply = html.escape(
        _truncate_text(str(pipeline.get("final_reply", "") or "—"), limit=320)
    )
    tool_lines = _tool_summary_lines(record)
    order_lines = _order_summary_lines(_record_tool_output(record))
    warnings = _record_warnings(record)
    next_action = html.escape(_recommended_next_action(record))
    record_id = html.escape(str(record.get("record_id", "—")))
    room_id = html.escape(str(record.get("room_id", "—")))
    target_message_id = html.escape(str(record.get("target_message_id", "—")))
    reply_source = html.escape(str(pipeline.get("final_reply_source", "—")))

    badges = (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
        f'background:#ede9fe;color:#5b21b6;font-size:12px;font-weight:600;">'
        f'{html.escape(intent_label)}</span>'
        f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
        f'background:#dbeafe;color:#1d4ed8;font-size:12px;font-weight:600;">'
        f'{html.escape(action_label)}</span>'
        f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
        f'background:#e0f2fe;color:#075985;font-size:12px;font-weight:600;">'
        f'اطمینان {confidence}</span>'
        f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
        f'background:#fef3c7;color:#92400e;font-size:12px;font-weight:600;">'
        f'بررسی انسانی: {needs_review}</span>'
    )

    tools_block = ""
    if tool_lines:
        tool_items = "".join(
            f'<div style="margin-top:4px;">{html.escape(line)}</div>'
            for line in tool_lines
        )
        tools_block = (
            '<div style="margin-top:10px;padding:8px 10px;border-radius:8px;'
            'background:#ecfdf5;border:1px solid #86efac;">'
            '<div style="font-weight:600;color:#166534;margin-bottom:4px;">ابزارهای استفاده‌شده</div>'
            f"{tool_items}"
            "</div>"
        )

    order_block = ""
    if order_lines:
        order_items = "".join(
            f'<div style="margin-top:4px;">{html.escape(line)}</div>'
            for line in order_lines
        )
        order_block = (
            '<div style="margin-top:10px;padding:8px 10px;border-radius:8px;'
            'background:#f8fafc;border:1px solid #e2e8f0;">'
            '<div style="font-weight:600;color:#334155;margin-bottom:4px;">خلاصه سفارش / مرسوله</div>'
            f"{order_items}"
            "</div>"
        )

    warnings_block = ""
    if warnings:
        warning_items = "".join(
            f'<div style="margin-top:4px;">• {html.escape(item)}</div>'
            for item in warnings
        )
        warnings_block = (
            '<div style="margin-top:10px;padding:8px 10px;border-radius:8px;'
            'background:#fffbeb;border:1px solid #fcd34d;">'
            '<div style="font-weight:600;color:#92400e;margin-bottom:4px;">هشدارها</div>'
            f"{warning_items}"
            "</div>"
        )

    return (
        '<div dir="rtl" style="font-family:Tahoma,Arial,sans-serif;border:1px solid #dbeafe;'
        'border-radius:12px;padding:12px;background:#f8fbff;color:#1f2937;line-height:1.8;">'
        '<div style="font-weight:700;color:#1d4ed8;margin-bottom:8px;">'
        "🤖 پیشنهاد هوش مصنوعی برای ادمین"
        "</div>"
        f'<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;">{badges}</div>'
        '<div style="margin-top:8px;padding:8px 10px;border-radius:8px;background:#ffffff;'
        'border:1px solid #e5e7eb;">'
        '<div style="font-weight:600;color:#374151;margin-bottom:4px;">خلاصه درخواست فروشنده</div>'
        f'<div style="font-size:13px;">{seller_summary}</div>'
        "</div>"
        '<div style="margin-top:10px;padding:8px 10px;border-radius:8px;background:#ffffff;'
        'border:1px solid #e5e7eb;">'
        '<div style="font-weight:600;color:#374151;margin-bottom:4px;">پیش‌نمایش پاسخ AI</div>'
        f'<div style="font-size:13px;">{final_reply}</div>'
        "</div>"
        f"{tools_block}{order_block}{warnings_block}"
        '<div style="margin-top:10px;padding:8px 10px;border-radius:8px;background:#eff6ff;'
        'border:1px solid #bfdbfe;">'
        '<div style="font-weight:600;color:#1d4ed8;margin-bottom:4px;">اقدام بعدی پیشنهادی</div>'
        f'<div style="font-size:13px;">{next_action}</div>'
        "</div>"
        '<div style="margin-top:10px;padding:8px 10px;border-radius:8px;background:#f3f4f6;'
        'border:1px solid #d1d5db;font-size:11px;color:#6b7280;">'
        f"record: {record_id} | room: {room_id} | message: {target_message_id} | "
        f"source: {reply_source}"
        "</div>"
        "</div>"
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
    return _send_message(
        record=record,
        message_type=3,
        content=build_admin_suggestion_content(record),
        meta=build_admin_suggestion_meta(record),
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
