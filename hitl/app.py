"""Streamlit live HITL review console."""

from __future__ import annotations

import html
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from hitl.jalali import to_jalali
from hitl.sender import parse_refer_to, send_both, send_reply, send_suggestion
from hitl.state import (
    FEEDBACK_LABELS,
    can_send,
    compute_metrics,
    get_record,
    load_records,
    update_record,
)

_SELLER_SENDERS = {"shop", "seller"}
_SUPPORT_SENDERS = {"admin", "support", "system"}
_TIMELINE_LABELS = {
    "seller": "فروشنده",
    "support": "پشتیبانی",
    "ai": "AI",
}
_QUEUE_PREVIEW_LEN = 48
_TOOL_DISPLAY = {
    "order_lookup": "order_lookup",
    "iran_post_tracking": "iran_post_tracking",
    "product_lookup": "product_lookup",
    "shop_lookup": "shop_lookup",
}
_EVIDENCE_TYPE_LABELS = {
    "order_status": "وضعیت سفارش",
    "shipment_status": "وضعیت مرسوله",
    "tracking_status": "رهگیری مرسوله",
    "tool_failure": "خطای ابزار",
    "unsupported_carrier": "شرکت حمل پشتیبانی‌نشده",
    "missing_required_entity": "اطلاعات ناقص",
}
_FEEDBACK_BUTTONS = [
    ("صحیح", "correct"),
    ("اشتباه در قصد", "wrong_intent"),
    ("اشتباه در پاسخ", "wrong_reply"),
    ("ابزار اشتباه", "wrong_tool"),
    ("ابزار استفاده نشده", "missing_tool"),
]
_INTENT_CORRECTION_OPTIONS = [
    "delivery_confirmation",
    "tracking_code_update",
    "address_correction",
    "product_approval_followup",
    "product_change_request",
    "settlement_inquiry",
    "account_activation_request",
    "cancellation_request",
    "complaint_order_followup",
    "general_inquiry",
    "other",
]
_STATUS_LABELS = {
    "pending_review": "در انتظار بررسی",
    "send_attempted": "در حال ارسال",
    "send_failed": "خطا در ارسال",
    "sent": "ارسال شد",
    "suggested": "پیشنهاد ارسال شد",
    "sent_both": "هر دو ارسال شد",
    "rejected_local": "رد شد",
    "error": "خطا",
}


@st.cache_data(ttl=10)
def _cached_records(state_path: str) -> list[dict[str, Any]]:
    return load_records(Path(state_path))


def _pipeline_field(record: dict[str, Any], key: str, default: str = "") -> str:
    return str(record.get("pipeline", {}).get(key, default))


def _inject_global_css() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 0.5rem; padding-bottom: 0.5rem; max-width: 100%; }
        div[data-testid="column"] > div { padding-top: 0; }
        section[data-testid="stSidebar"] {
            min-width: 14rem !important;
            max-width: 14rem !important;
        }
        section[data-testid="stSidebar"] .block-container { padding-top: 0.5rem; }
        section[data-testid="stSidebar"] [data-testid="stMetric"] {
            background: #f8fafc;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 6px 8px;
            margin-bottom: 4px;
        }
        section[data-testid="stSidebar"] [data-testid="stMetricLabel"] {
            font-size: 11px;
        }
        section[data-testid="stSidebar"] [data-testid="stMetricValue"] {
            font-size: 18px;
        }
        h3 { margin-top: 0.25rem; margin-bottom: 0.35rem; font-size: 1rem; }
        .hitl-summary {
            display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center;
            background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 10px;
            padding: 8px 12px; margin-bottom: 8px; font-size: 13px;
        }
        .hitl-summary .chip {
            background: #fff; border: 1px solid #e5e7eb; border-radius: 999px;
            padding: 3px 10px; white-space: nowrap;
        }
        .hitl-summary .chip strong { color: #6b7280; font-weight: 600; }
        div[data-testid="stDataFrame"] { font-size: 12px; }
        div[data-testid="stDataFrame"] thead th {
            position: sticky;
            top: 0;
            z-index: 2;
            background: #f8fafc;
        }
        div[data-testid="stDataFrame"] [data-testid="stDataFrameResizable"] {
            max-height: 920px;
        }
        div.stButton > button { border-radius: 8px; font-weight: 600; padding: 0.35rem 0.6rem; }
        div[data-testid="stVerticalBlock"] > div { gap: 0.35rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_filter_toolbar(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered = records
    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        statuses = st.multiselect(
            "وضعیت",
            sorted({str(record.get("status", "")) for record in records}),
            default=[],
            key="filter_status",
        )
    with c2:
        room_types = st.multiselect(
            "نوع اتاق",
            sorted(
                {
                    str(record.get("room_type", ""))
                    for record in records
                    if record.get("room_type")
                }
            ),
            default=[],
            key="filter_room_type",
        )
    with c3:
        intents = st.multiselect(
            "قصد",
            sorted(
                {
                    str(record.get("pipeline", {}).get("primary_intent", ""))
                    for record in records
                    if record.get("pipeline", {}).get("primary_intent")
                }
            ),
            default=[],
            key="filter_intent",
        )
    with c4:
        review_filter = st.selectbox(
            "بررسی انسانی",
            ["همه", "بله", "خیر"],
            key="filter_human_review",
        )
    with c5:
        tool_filter = st.selectbox(
            "ابزار",
            ["همه", "order_lookup", "iran_post_tracking"],
            key="filter_tool",
        )

    if statuses:
        filtered = [record for record in filtered if record.get("status") in statuses]
    if room_types:
        filtered = [record for record in filtered if record.get("room_type") in room_types]
    if intents:
        filtered = [
            record
            for record in filtered
            if _pipeline_field(record, "primary_intent") in intents
        ]
    if review_filter == "بله":
        filtered = [
            record
            for record in filtered
            if record.get("pipeline", {}).get("needs_human_review") is True
        ]
    elif review_filter == "خیر":
        filtered = [
            record
            for record in filtered
            if record.get("pipeline", {}).get("needs_human_review") is not True
        ]
    if tool_filter != "همه":
        filtered = [
            record
            for record in filtered
            if tool_filter in record.get("pipeline", {}).get("selected_tools", [])
        ]
    return filtered


def _filter_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _render_filter_toolbar(records)


def _record_timestamp(record: dict[str, Any]) -> float:
    raw = str(record.get("created_at", ""))
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def sort_queue_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        records,
        key=lambda record: (
            0 if record.get("status") == "pending_review" else 1,
            -_record_timestamp(record),
        ),
    )


def truncate_preview(text: str, limit: int = _QUEUE_PREVIEW_LEN) -> str:
    cleaned = " ".join(str(text).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _format_confidence(pipeline: dict[str, Any]) -> str:
    confidence = pipeline.get("confidence")
    if isinstance(confidence, (int, float)):
        return f"{float(confidence):.0%}"
    return "—"


def _record_tool_output(record: dict[str, Any]) -> list[dict[str, Any]]:
    pipeline = record.get("pipeline", {})
    output = record.get("tool_output")
    if isinstance(output, list) and output:
        return output
    safe_output = pipeline.get("safe_tool_output")
    if isinstance(safe_output, list):
        return safe_output
    return []


def _record_tool_status(record: dict[str, Any]) -> dict[str, Any]:
    pipeline = record.get("pipeline", {})
    status = pipeline.get("tool_status")
    if isinstance(status, dict):
        return status
    return {}


def _record_warnings(record: dict[str, Any]) -> list[str]:
    pipeline = record.get("pipeline", {})
    warnings: list[str] = []
    for source in (record.get("warnings"), pipeline.get("warnings")):
        if isinstance(source, list):
            for item in source:
                text = str(item).strip()
                if text and text not in warnings:
                    warnings.append(text)
    return warnings


def _record_evidence_items(record: dict[str, Any]) -> list[dict[str, Any]]:
    pipeline = record.get("pipeline", {})
    items = pipeline.get("evidence_items")
    if not isinstance(items, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary", "")).strip()
        if not summary:
            continue
        source_tool = str(item.get("source_tool", "")).strip() or None
        evidence_type = str(item.get("evidence_type", "")).strip()
        normalized.append(
            {
                "evidence_type": evidence_type,
                "source_tool": source_tool,
                "confidence": item.get("confidence", 1.0),
                "summary": summary,
            }
        )
    return normalized


def _evidence_type_label(evidence_type: str) -> str:
    if not evidence_type:
        return ""
    return _EVIDENCE_TYPE_LABELS.get(evidence_type, evidence_type.replace("_", " "))


def _evidence_confidence_text(confidence: Any) -> str | None:
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return None
    if abs(value - 1.0) < 0.0001:
        return None
    return f"{value:.0%}"


def build_evidence_views(record: dict[str, Any]) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    for item in _record_evidence_items(record):
        evidence_type = item["evidence_type"]
        views.append(
            {
                "summary": item["summary"],
                "source_tool": item["source_tool"],
                "evidence_type": evidence_type,
                "type_label": _evidence_type_label(evidence_type),
                "confidence_text": _evidence_confidence_text(item.get("confidence", 1.0)),
            }
        )
    return views


def build_evidence_html(record: dict[str, Any]) -> str:
    views = build_evidence_views(record)
    if not views:
        return '<div class="evidence-empty">شواهدی ثبت نشده است.</div>'

    rows: list[str] = []
    for view in views:
        meta_parts: list[str] = []
        if view.get("source_tool"):
            meta_parts.append(
                f'<span class="evidence-chip tool">{html.escape(view["source_tool"])}</span>'
            )
        type_label = view.get("type_label", "")
        if type_label:
            meta_parts.append(
                f'<span class="evidence-chip type">{html.escape(type_label)}</span>'
            )
        confidence_text = view.get("confidence_text")
        if confidence_text:
            meta_parts.append(
                f'<span class="evidence-chip conf">{html.escape(confidence_text)}</span>'
            )
        meta_html = ""
        if meta_parts:
            meta_html = (
                '<div class="evidence-meta">'
                + '<span class="evidence-sep">·</span>'.join(meta_parts)
                + "</div>"
            )
        rows.append(
            f'<div class="evidence-row">'
            f'<span class="evidence-icon">✓</span>'
            f'<div class="evidence-body">'
            f'<div class="evidence-summary">{html.escape(view["summary"])}</div>'
            f"{meta_html}"
            f"</div></div>"
        )

    return f'<div class="evidence-card">{"".join(rows)}</div>'


def _order_lookup_summary_lines(outputs: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in outputs:
        order_id = str(item.get("order_id", "")).strip()
        if not order_id:
            continue
        lines.append(f"Order: {order_id}")
        order_status = str(item.get("order_status", "")).strip()
        if order_status:
            lines.append(f"Status: {order_status}")
        parcel_status = str(item.get("parcel_status", "")).strip()
        if parcel_status:
            lines.append(f"Parcel Status: {parcel_status}")
        tracking_code = str(item.get("tracking_code", "")).strip()
        if tracking_code:
            lines.append(f"Tracking Code: {tracking_code}")
    return lines


def _iran_post_summary_lines(outputs: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in outputs:
        tracking_code = str(item.get("tracking_code", "")).strip()
        if not tracking_code:
            continue
        lines.append(f"Tracking Code: {tracking_code}")
        parcel_status = str(item.get("parcel_status", "")).strip()
        if parcel_status:
            lines.append(f"Current Status: {parcel_status}")
        break
    return lines


def _tool_status_code(
    tool_name: str,
    *,
    selected: set[str],
    tool_status: dict[str, Any],
    outputs: list[dict[str, Any]],
) -> str:
    if tool_name == "order_lookup":
        if tool_status.get("order_lookup_executed"):
            if tool_status.get("order_lookup_success") is True:
                return "success"
            return "failure"
        if outputs:
            return "success"
        if tool_name in selected:
            return "not_executed"
        return "not_selected"

    if tool_name == "iran_post_tracking":
        if tool_name not in selected:
            return "not_selected"
        if _iran_post_summary_lines(outputs):
            return "success"
        return "not_executed"

    if tool_name in selected:
        return "not_executed"
    return "not_selected"


def _tool_status_icon(status: str) -> str:
    if status == "success":
        return "✓"
    if status in {"failure", "not_executed"}:
        return "✗"
    return "—"


def build_tool_views(record: dict[str, Any]) -> list[dict[str, Any]]:
    pipeline = record.get("pipeline", {})
    selected = {str(tool) for tool in (pipeline.get("selected_tools") or [])}
    outputs = _record_tool_output(record)
    tool_status = _record_tool_status(record)
    warnings = _record_warnings(record)

    tool_names = set(selected)
    if outputs:
        tool_names.add("order_lookup")

    views: list[dict[str, Any]] = []
    for tool_name in (
        "order_lookup",
        "iran_post_tracking",
        "product_lookup",
        "shop_lookup",
    ):
        status = _tool_status_code(
            tool_name,
            selected=selected,
            tool_status=tool_status,
            outputs=outputs,
        )
        if status == "not_selected":
            continue

        summary: list[str] = []
        if tool_name == "order_lookup" and status == "success":
            summary = _order_lookup_summary_lines(outputs)
        elif tool_name == "iran_post_tracking" and status == "success":
            summary = _iran_post_summary_lines(outputs)

        views.append(
            {
                "name": tool_name,
                "label": _TOOL_DISPLAY.get(tool_name, tool_name),
                "status": status,
                "icon": _tool_status_icon(status),
                "summary": summary,
            }
        )

    error = tool_status.get("order_lookup_error")
    if isinstance(error, str) and error.strip() and error.strip() not in warnings:
        warnings.append(error.strip())

    return views


def format_queue_tools_label(record: dict[str, Any]) -> str:
    pipeline = record.get("pipeline", {})
    selected = list(pipeline.get("selected_tools") or [])
    outputs = _record_tool_output(record)
    labels: list[str] = []

    if "order_lookup" in selected or outputs:
        labels.append("order_lookup")
    if "iran_post_tracking" in selected:
        labels.append("tracking")
    for tool_name in selected:
        if tool_name in {"order_lookup", "iran_post_tracking"}:
            continue
        labels.append(tool_name.replace("_", " "))

    if not labels:
        return "—"
    return "🔧 " + " + ".join(labels)


def build_queue_dataframe(
    records: list[dict[str, Any]],
) -> tuple[pd.DataFrame, list[str]]:
    record_ids: list[str] = []
    rows: list[dict[str, str]] = []
    for record in records:
        record_ids.append(str(record.get("record_id", "")))
        pipeline = record.get("pipeline", {})
        rows.append(
            {
                "Time": str(record.get("created_at_jalali", "")),
                "Room": str(record.get("room_id", "")),
                "Shop": str(record.get("shop_id", "")),
                "Intent": _pipeline_field(record, "primary_intent", "—"),
                "Conf": _format_confidence(pipeline),
                "Status": _status_label(str(record.get("status", ""))),
                "Tools": format_queue_tools_label(record),
                "Message": truncate_preview(str(record.get("seller_message", ""))),
            }
        )
    return pd.DataFrame(rows), record_ids


def _classify_timeline_kind(item: dict[str, Any]) -> str:
    sender = str(item.get("sender", "")).lower()
    role = str(item.get("role", "")).lower()
    if sender in _SELLER_SENDERS or role == "user":
        return "seller"
    if sender in _SUPPORT_SENDERS or role == "assistant":
        return "support"
    return "support"


def _timeline_label_for_item(item: dict[str, Any], kind: str) -> str:
    if kind == "ai":
        return _TIMELINE_LABELS["ai"]
    for key in ("sender_display_name", "sender_name", "display_name"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return _TIMELINE_LABELS[kind]


def build_send_preview(record: dict[str, Any]) -> dict[str, Any]:
    pipeline = record.get("pipeline", {})
    tools = [
        f"✓ {view['name']}"
        for view in build_tool_views(record)
        if view.get("icon") == "✓"
    ]
    return {
        "content": str(pipeline.get("final_reply", "")),
        "intent": str(pipeline.get("primary_intent", "—")),
        "confidence": _format_confidence(pipeline),
        "tools": tools,
    }


def _item_timestamp(item: dict[str, Any], fallback: str | None = None) -> str | None:
    for key in ("created_at_jalali", "timestamp", "created_at"):
        value = item.get(key)
        if value:
            return str(value)
    return fallback


def format_timeline_timestamp(value: str | None) -> str:
    if not value:
        return "—"
    if len(value) <= 18 and value.count("-") >= 2 and value[2] == "-":
        return value
    try:
        return to_jalali(value)
    except ValueError:
        return value


def build_timeline_messages(record: dict[str, Any]) -> list[dict[str, Any]]:
    target_id = str(record.get("target_message_id", ""))
    stored = record.get("timeline_messages")
    if isinstance(stored, list) and stored:
        timeline: list[dict[str, Any]] = []
        for index, item in enumerate(stored):
            message_id = item.get("id")
            item_id = str(message_id) if message_id is not None else f"timeline-{index}"
            kind = _classify_timeline_kind(item)
            timeline.append(
                {
                    "message_id": item_id,
                    "kind": kind,
                    "label": _timeline_label_for_item(item, kind),
                    "content": str(item.get("content", "")),
                    "timestamp": _item_timestamp(item),
                    "is_target": bool(item.get("is_target"))
                    or (target_id and item_id == target_id),
                    "sort_key": (0, index),
                }
            )
    else:
        timeline = []
        seen_ids: set[str] = set()

        for index, item in enumerate(record.get("conversation_context", [])):
            message_id = item.get("id")
            item_id = str(message_id) if message_id is not None else f"context-{index}"
            kind = _classify_timeline_kind(item)
            timeline.append(
                {
                    "message_id": item_id,
                    "kind": kind,
                    "label": _timeline_label_for_item(item, kind),
                    "content": str(item.get("content", "")),
                    "timestamp": _item_timestamp(item),
                    "is_target": item_id == target_id,
                    "sort_key": (0, index),
                }
            )
            seen_ids.add(item_id)

        if target_id and target_id not in seen_ids:
            timeline.append(
                {
                    "message_id": target_id,
                    "kind": "seller",
                    "label": _TIMELINE_LABELS["seller"],
                    "content": str(record.get("seller_message", "")),
                    "timestamp": record.get("created_at_jalali") or record.get("created_at"),
                    "is_target": True,
                    "sort_key": (1, int(target_id) if target_id.isdigit() else target_id),
                }
            )
        else:
            for message in timeline:
                if str(message["message_id"]) == target_id:
                    message["is_target"] = True

    final_reply = str(record.get("pipeline", {}).get("final_reply", "")).strip()
    if final_reply:
        timeline.append(
            {
                "message_id": f"ai-{target_id or record.get('record_id', 'reply')}",
                "kind": "ai",
                "label": _TIMELINE_LABELS["ai"],
                "content": final_reply,
                "timestamp": record.get("created_at_jalali") or record.get("created_at"),
                "is_target": False,
                "sort_key": (2, 0),
            }
        )

    return timeline


def _timeline_bubble_css(kind: str, is_target: bool) -> str:
    if kind == "seller":
        css = (
            "background:#dbeafe;border:1px solid #93c5fd;"
            "margin-left:auto;margin-right:0;"
        )
    elif kind == "ai":
        css = (
            "background:#dcfce7;border:1px solid #86efac;"
            "margin-left:0;margin-right:auto;"
        )
    else:
        css = (
            "background:#f3f4f6;border:1px solid #d1d5db;"
            "margin-left:0;margin-right:auto;"
        )
    if is_target:
        css += "border:2px solid #f59e0b;box-shadow:0 0 0 2px #f59e0b33;"
    return css


def build_timeline_html(record: dict[str, Any], *, auto_scroll: bool) -> str:
    messages = build_timeline_messages(record)
    target_id = html.escape(str(record.get("target_message_id", "")), quote=True)
    target_anchor = f"target-message-{target_id}"
    rows: list[str] = []

    for message in messages:
        message_id = html.escape(str(message["message_id"]), quote=True)
        anchor = target_anchor if message.get("is_target") else f"timeline-message-{message_id}"
        timestamp = html.escape(format_timeline_timestamp(message.get("timestamp")))
        label = html.escape(message["label"])
        content = html.escape(message.get("content", "")).replace("\n", "<br>")
        align = "flex-end" if message["kind"] == "seller" else "flex-start"
        badge = (
            '<span class="target-badge">پیام فعلی</span>'
            if message.get("is_target")
            else ""
        )
        rows.append(
            f'<div class="row" style="justify-content:{align};">'
            f'<div id="{anchor}" class="bubble" style="{_timeline_bubble_css(message["kind"], bool(message.get("is_target")))}">'
            f'<div class="meta">{badge}<span>{label}</span><span class="time">{timestamp}</span></div>'
            f'<div class="content">{content}</div>'
            f"</div></div>"
        )

    scroll_script = ""
    if auto_scroll and target_id:
        scroll_script = f"""
        <script>
        window.addEventListener('load', function() {{
          var box = document.getElementById('conversation-timeline');
          var target = document.getElementById('{target_anchor}');
          if (box && target) {{
            box.scrollTop = Math.max(0, target.offsetTop - box.clientHeight / 2);
          }}
        }});
        </script>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="fa" dir="rtl">
    <head>
      <meta charset="utf-8">
      <style>
        body {{
          margin: 0;
          font-family: Tahoma, Arial, sans-serif;
          background: #f8fafc;
          direction: rtl;
        }}
        #conversation-timeline {{
          max-height: 360px;
          overflow-y: auto;
          padding: 8px;
          background: #f8fafc;
        }}
        .row {{ display: flex; margin: 6px 0; }}
        .bubble {{
          max-width: 78%;
          padding: 8px 10px;
          border-radius: 14px;
          line-height: 1.65;
          word-break: break-word;
        }}
        .meta {{
          display: flex;
          gap: 8px;
          align-items: center;
          font-size: 12px;
          color: #4b5563;
          margin-bottom: 6px;
          flex-wrap: wrap;
        }}
        .time {{ color: #6b7280; }}
        .content {{ font-size: 15px; color: #111827; text-align: right; }}
        .target-badge {{
          background: #fef3c7;
          color: #92400e;
          border: 1px solid #f59e0b;
          border-radius: 999px;
          padding: 2px 8px;
          font-size: 11px;
        }}
        .toolbar {{
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 8px 12px 0 12px;
          color: #6b7280;
          font-size: 13px;
        }}
        .toolbar a {{
          color: #b45309;
          text-decoration: none;
          background: #fff7ed;
          border: 1px solid #fdba74;
          border-radius: 8px;
          padding: 5px 10px;
          font-size: 12px;
        }}
      </style>
    </head>
    <body>
      <div class="toolbar">
        <span>{len(messages)} پیام</span>
        <a href="#{target_anchor}">رفتن به پیام فعلی</a>
      </div>
      <div id="conversation-timeline">
        {''.join(rows) if rows else '<div style="padding:12px;color:#6b7280;">پیامی موجود نیست</div>'}
      </div>
      {scroll_script}
    </body>
    </html>
    """


def _render_conversation_timeline(record: dict[str, Any]) -> None:
    record_id = str(record.get("record_id", ""))
    st.markdown("#### گفتگو")
    scroll_key = f"timeline_scrolled_{record_id}"
    auto_scroll = scroll_key not in st.session_state
    if auto_scroll:
        st.session_state[scroll_key] = True
    components.html(
        build_timeline_html(record, auto_scroll=auto_scroll),
        height=400,
        scrolling=False,
    )


def _bool_badge(value: Any) -> str:
    if value is True:
        return '<span class="pill yes">بله</span>'
    if value is False:
        return '<span class="pill no">خیر</span>'
    return '<span class="pill neutral">—</span>'


def _render_tools_section(record: dict[str, Any]) -> None:
    pipeline = record.get("pipeline", {})
    selected = pipeline.get("selected_tools") or []
    views = build_tool_views(record)
    warnings = _record_warnings(record)
    executed = [view["label"] for view in views if view["status"] == "success"]

    st.markdown("#### ابزارهای استفاده‌شده")
    if not selected and not views and not warnings:
        st.caption("ابزاری انتخاب یا اجرا نشده است.")
        return

    selected_html = " ".join(
        f'<span class="tool-chip selected">{html.escape(str(tool))}</span>'
        for tool in selected
    ) or '<span class="tool-chip muted">—</span>'
    executed_html = " ".join(
        f'<span class="tool-chip executed">{html.escape(tool)}</span>'
        for tool in executed
    ) or '<span class="tool-chip muted">—</span>'
    warning_html = " ".join(
        f'<span class="tool-chip warn">{html.escape(item)}</span>'
        for item in warnings
    ) or '<span class="tool-chip muted">—</span>'

    tool_rows: list[str] = []
    for view in views:
        summary_html = ""
        if view["summary"]:
            summary_html = "<ul>" + "".join(
                f"<li>{html.escape(line)}</li>" for line in view["summary"]
            ) + "</ul>"
        status_class = view["status"]
        tool_rows.append(
            f'<div class="tool-row">'
            f'<span class="tool-status {status_class}">{view["icon"]}</span>'
            f'<span class="tool-name">{html.escape(view["label"])}</span>'
            f"{summary_html}"
            f"</div>"
        )

    st.markdown(
        f"""
        <div class="tools-card">
          <div class="tools-meta">
            <div><span class="meta-label">انتخاب‌شده</span>{selected_html}</div>
            <div><span class="meta-label">اجرا شده</span>{executed_html}</div>
            <div><span class="meta-label">هشدار</span>{warning_html}</div>
          </div>
          {''.join(tool_rows) if tool_rows else '<div class="tool-empty">خلاصه ابزار موجود نیست</div>'}
        </div>
        <style>
        .tools-card {{
          border:1px solid #e5e7eb;border-radius:10px;padding:10px 12px;background:#fff;
        }}
        .tools-meta {{
          display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;
          margin-bottom:8px;font-size:12px;
        }}
        .meta-label {{ color:#6b7280; display:block; margin-bottom:4px; }}
        .tool-chip {{
          display:inline-block;padding:2px 8px;border-radius:999px;
          font-size:11px;font-weight:600;margin:2px 2px 0 0;
        }}
        .tool-chip.selected {{ background:#eef2ff;color:#3730a3; }}
        .tool-chip.executed {{ background:#dcfce7;color:#166534; }}
        .tool-chip.warn {{ background:#fff7ed;color:#9a3412; }}
        .tool-chip.muted {{ background:#f3f4f6;color:#6b7280; }}
        .tool-row {{
          display:flex;gap:8px;align-items:flex-start;padding:6px 0;
          border-top:1px solid #f1f5f9;font-size:13px;
        }}
        .tool-status {{ font-weight:700; min-width:14px; }}
        .tool-status.success {{ color:#16a34a; }}
        .tool-status.failure, .tool-status.not_executed {{ color:#dc2626; }}
        .tool-name {{ font-weight:600;color:#111827;min-width:130px; }}
        .tool-row ul {{ margin:0;padding:0 18px 0 0;color:#374151; }}
        .tool-row li {{ margin:2px 0; }}
        .tool-empty {{ color:#6b7280;font-size:12px; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_evidence_section(record: dict[str, Any]) -> None:
    st.markdown("#### شواهد بررسی‌شده")
    st.markdown(
        f"""
        {build_evidence_html(record)}
        <style>
        .evidence-card {{
          border:1px solid #e5e7eb;border-radius:10px;padding:10px 12px;background:#fff;
        }}
        .evidence-empty {{
          color:#6b7280;font-size:13px;
        }}
        .evidence-row {{
          display:flex;gap:8px;align-items:flex-start;padding:6px 0;
          border-top:1px solid #f1f5f9;font-size:13px;
        }}
        .evidence-row:first-child {{ border-top:none;padding-top:0; }}
        .evidence-icon {{ color:#16a34a;font-weight:700;min-width:14px; }}
        .evidence-summary {{ color:#111827;line-height:1.5; }}
        .evidence-meta {{
          margin-top:4px;display:flex;flex-wrap:wrap;gap:4px;align-items:center;
          font-size:11px;color:#6b7280;
        }}
        .evidence-chip {{
          display:inline-block;padding:1px 7px;border-radius:999px;
          font-size:11px;font-weight:600;
        }}
        .evidence-chip.tool {{ background:#eef2ff;color:#3730a3; }}
        .evidence-chip.type {{ background:#f3f4f6;color:#374151; }}
        .evidence-chip.conf {{ background:#e0f2fe;color:#075985; }}
        .evidence-sep {{ color:#9ca3af;padding:0 2px; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_ai_reply_card(record: dict[str, Any]) -> None:
    pipeline = record.get("pipeline", {})
    final_reply = html.escape(str(pipeline.get("final_reply", ""))).replace("\n", "<br>")
    warnings = pipeline.get("warnings", []) or record.get("warnings", [])
    warning_items = warnings or ["—"]
    warning_html = "".join(
        f'<span class="pill warn">{html.escape(str(item))}</span>'
        for item in warning_items
    )
    intent = html.escape(str(pipeline.get("primary_intent", "—")))
    confidence_text = html.escape(_format_confidence(pipeline))
    action = html.escape(str(pipeline.get("suggested_action", "—")))

    st.markdown("#### بررسی AI")
    st.markdown(
        f"""
        <div class="ai-card">
          <div class="ai-reply" dir="rtl">{final_reply or "—"}</div>
          <div class="badge-row">
            <span class="label">قصد</span><span class="pill intent">{intent}</span>
            <span class="label">اطمینان</span><span class="pill conf">{confidence_text}</span>
            <span class="label">اقدام</span><span class="pill action">{action}</span>
            <span class="label">بررسی</span>{_bool_badge(pipeline.get("needs_human_review"))}
            <span class="label">ارسال</span>{_bool_badge(pipeline.get("should_send"))}
            <span class="label">هشدار</span>{warning_html}
          </div>
        </div>
        <style>
        .ai-card {{
          background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:10px 12px;
        }}
        .ai-reply {{
          font-size:14px;line-height:1.6;margin-bottom:8px;padding:8px 10px;
          background:#f8fafc;border-radius:8px;border:1px solid #e5e7eb;
        }}
        .badge-row {{
          display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;font-size:12px;
        }}
        .label {{ color:#6b7280;font-weight:600; }}
        .pill {{
          display:inline-block;padding:2px 8px;border-radius:999px;
          font-size:12px;font-weight:600;
        }}
        .pill.intent {{ background:#ede9fe;color:#5b21b6; }}
        .pill.conf {{ background:#e0f2fe;color:#075985; }}
        .pill.action {{ background:#fef3c7;color:#92400e; }}
        .pill.yes {{ background:#dcfce7;color:#166534; }}
        .pill.no {{ background:#fee2e2;color:#991b1b; }}
        .pill.neutral {{ background:#f3f4f6;color:#374151; }}
        .pill.warn {{ background:#fff7ed;color:#9a3412; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_send_preview_card(record: dict[str, Any]) -> None:
    preview = build_send_preview(record)
    content = html.escape(preview["content"]).replace("\n", "<br>")
    intent = html.escape(preview["intent"])
    confidence = html.escape(preview["confidence"])
    if preview["tools"]:
        tools_html = "".join(
            f'<div class="preview-tool">{html.escape(tool)}</div>'
            for tool in preview["tools"]
        )
        tools_block = (
            '<div class="preview-tools">'
            '<div class="preview-tools-title">Generated from:</div>'
            f"{tools_html}"
            "</div>"
        )
    else:
        tools_block = '<div class="preview-tools muted">Generated from: —</div>'

    st.markdown("#### پیش‌نمایش پاسخ ارسالی")
    st.markdown(
        f"""
        <div class="send-preview-card">
          <div class="send-preview-text" dir="rtl">{content or "—"}</div>
          <div class="send-preview-meta">
            <span class="label">قصد</span><span class="pill intent">{intent}</span>
            <span class="label">اطمینان</span><span class="pill conf">{confidence}</span>
          </div>
          {tools_block}
        </div>
        <style>
        .send-preview-card {{
          background:#fff;border:1px solid #dbeafe;border-radius:10px;padding:10px 12px;
        }}
        .send-preview-text {{
          font-size:14px;line-height:1.6;margin-bottom:8px;padding:8px 10px;
          background:#eff6ff;border-radius:8px;border:1px solid #bfdbfe;
        }}
        .send-preview-meta {{
          display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;font-size:12px;
          margin-bottom:8px;
        }}
        .preview-tools {{ font-size:12px;color:#1f2937; }}
        .preview-tools.muted {{ color:#6b7280; }}
        .preview-tools-title {{ font-weight:600;margin-bottom:4px;color:#374151; }}
        .preview-tool {{ padding:2px 0;font-family:ui-monospace,monospace; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _save_feedback(record_id: str, label: str, comment: str) -> None:
    current = get_record(record_id)
    feedback = dict((current or {}).get("feedback") or {})
    feedback.update(
        {
            "label": label,
            "comment": comment,
            "created_at_jalali": to_jalali(),
        }
    )
    update_record(record_id, {"feedback": feedback})


def merge_intent_feedback(
    existing_feedback: dict[str, Any] | None,
    *,
    intent_correct: bool,
    correct_intent: str | None = None,
) -> dict[str, Any]:
    feedback = dict(existing_feedback or {})
    feedback["intent_correct"] = intent_correct
    if intent_correct:
        feedback.pop("correct_intent", None)
    else:
        if not correct_intent:
            raise ValueError("missing_correct_intent")
        feedback["correct_intent"] = correct_intent
    feedback["intent_feedback_at_jalali"] = to_jalali()
    return feedback


def _save_intent_feedback(
    record_id: str,
    *,
    intent_correct: bool,
    correct_intent: str | None = None,
) -> None:
    current = get_record(record_id)
    feedback = merge_intent_feedback(
        (current or {}).get("feedback"),
        intent_correct=intent_correct,
        correct_intent=correct_intent,
    )
    update_record(record_id, {"feedback": feedback})


def _handle_send(
    record: dict[str, Any],
    action: str,
    refer_to_raw: str,
    request_fn=None,
) -> str | None:
    record_id = str(record["record_id"])
    current = get_record(record_id)
    if current is None or not can_send(str(current.get("status", ""))):
        st.error("ارسال مجاز نیست: وضعیت رکورد قابل ارسال نیست.")
        return None

    try:
        refer_to = parse_refer_to(refer_to_raw)
    except ValueError:
        st.error("ارجاع باید خالی یا یک عدد صحیح باشد.")
        return None

    update_record(record_id, {"status": "send_attempted"})
    logs = list(current.get("send_log", []))
    status = "send_attempted"

    if action == "reply":
        result = send_reply(current, refer_to=refer_to, request_fn=request_fn)
        logs.append(result)
        status = "sent" if result.get("success") else "send_failed"
        update_record(record_id, {"status": status, "send_log": logs})
    elif action == "suggestion":
        result = send_suggestion(current, refer_to=refer_to, request_fn=request_fn)
        logs.append(result)
        status = "suggested" if result.get("success") else "send_failed"
        update_record(record_id, {"status": status, "send_log": logs})
    elif action == "both":
        results = send_both(current, refer_to=refer_to, request_fn=request_fn)
        logs.extend(results)
        reply_ok = results[0].get("success")
        suggestion_ok = results[1].get("success")
        if reply_ok and suggestion_ok:
            status = "sent_both"
        elif reply_ok:
            status = "sent"
        elif suggestion_ok:
            status = "suggested"
        else:
            status = "send_failed"
        update_record(record_id, {"status": status, "send_log": logs})
    elif action == "reject":
        status = "rejected_local"
        update_record(record_id, {"status": status})
    elif action == "retry":
        last_action = st.session_state.get(f"retry_action_{record_id}", "reply")
        return _handle_send(record, last_action, refer_to_raw, request_fn=request_fn)

    return status


def _status_label(status: str) -> str:
    return _STATUS_LABELS.get(status, status)


def _render_queue_table(records: list[dict[str, Any]]) -> None:
    st.markdown("#### صف بررسی")
    st.caption(f"{len(records)} رکورد")
    selected_id = st.session_state.get("selected_record_id")
    frame, record_ids = build_queue_dataframe(records)
    if frame.empty:
        st.info("رکوردی برای نمایش نیست.")
        return

    table_height = min(28 * len(frame) + 38, 28 * 30 + 38)
    selection = st.dataframe(
        frame,
        hide_index=True,
        use_container_width=True,
        height=table_height,
        on_select="rerun",
        selection_mode="single-row",
    )
    selected_rows = getattr(getattr(selection, "selection", None), "rows", None) or []
    if selected_rows:
        row_index = selected_rows[0]
        if 0 <= row_index < len(record_ids):
            new_id = record_ids[row_index]
            if new_id != selected_id:
                st.session_state.selected_record_id = new_id
                st.session_state.pop(f"timeline_scrolled_{new_id}", None)
                st.rerun()
    elif selected_id not in record_ids and record_ids:
        st.session_state.selected_record_id = record_ids[0]


def _render_room_summary(record: dict[str, Any]) -> None:
    status = _status_label(str(record.get("status", "")))
    st.markdown(
        f"""
        <div class="hitl-summary" dir="rtl">
          <span class="chip"><strong>اتاق</strong> {html.escape(str(record.get("room_id", "")))}</span>
          <span class="chip"><strong>فروشگاه</strong> {html.escape(str(record.get("shop_id", "")))}</span>
          <span class="chip"><strong>نوع</strong> {html.escape(str(record.get("room_type", "")))}</span>
          <span class="chip"><strong>پیام</strong> {html.escape(str(record.get("target_message_id", "")))}</span>
          <span class="chip"><strong>زمان</strong> {html.escape(str(record.get("created_at_jalali", "")))}</span>
          <span class="chip"><strong>وضعیت</strong> {html.escape(status)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar_metrics(metrics: dict[str, Any]) -> None:
    st.sidebar.header("آمار")
    st.sidebar.metric("processed", metrics.get("processed", 0))
    st.sidebar.metric("pending", metrics.get("pending", 0))
    st.sidebar.metric("sent", metrics.get("sent", 0))
    st.sidebar.metric("approval_rate", metrics.get("approval_rate", 0))
    with st.sidebar.expander("آمار تکمیلی"):
        for key in (
            "suggested",
            "rejected",
            "feedback_count",
            "wrong_intent_count",
            "wrong_reply_count",
            "missing_tool_count",
            "wrong_tool_count",
        ):
            if key in metrics:
                st.write(f"{key}: {metrics[key]}")
        st.write("top_intents", metrics.get("top_intents", []))
    st.sidebar.toggle("بروزرسانی خودکار (۱۰ ثانیه)", value=True, key="auto_refresh_toggle")


def _render_intent_feedback(record: dict[str, Any]) -> None:
    record_id = str(record["record_id"])
    predicted_intent = _pipeline_field(record, "primary_intent", "—")
    existing = record.get("feedback") or {}
    show_wrong_ui = st.session_state.get(f"intent_wrong_{record_id}", False)

    st.markdown("#### Intent Feedback")
    st.markdown(f"**Current Intent:** `{predicted_intent}`")

    if existing.get("intent_correct") is True:
        st.caption("✓ Intent marked correct")
    elif existing.get("intent_correct") is False:
        st.caption(f"✗ Correct intent: `{existing.get('correct_intent', '—')}`")

    ok_col, wrong_col = st.columns(2)
    with ok_col:
        if st.button(
            "✓ Intent Correct",
            key=f"intent_ok_{record_id}",
            use_container_width=True,
        ):
            _save_intent_feedback(record_id, intent_correct=True)
            st.session_state.pop(f"intent_wrong_{record_id}", None)
            _cached_records.clear()
            st.rerun()
    with wrong_col:
        if st.button(
            "✗ Intent Wrong",
            key=f"intent_wrong_btn_{record_id}",
            use_container_width=True,
        ):
            st.session_state[f"intent_wrong_{record_id}"] = True
            st.rerun()

    if show_wrong_ui or existing.get("intent_correct") is False:
        current_correct = existing.get("correct_intent")
        default_index = (
            _INTENT_CORRECTION_OPTIONS.index(current_correct)
            if current_correct in _INTENT_CORRECTION_OPTIONS
            else 0
        )
        selected = st.selectbox(
            "Correct intent",
            _INTENT_CORRECTION_OPTIONS,
            index=default_index,
            key=f"correct_intent_{record_id}",
        )
        if st.button("Save intent correction", key=f"save_intent_{record_id}"):
            _save_intent_feedback(
                record_id,
                intent_correct=False,
                correct_intent=selected,
            )
            st.session_state.pop(f"intent_wrong_{record_id}", None)
            _cached_records.clear()
            st.rerun()


def _render_feedback(record: dict[str, Any]) -> None:
    record_id = str(record["record_id"])
    existing = record.get("feedback") or {}
    if existing.get("label"):
        st.caption(
            f"بازخورد: {existing.get('label')} ({existing.get('created_at_jalali', '')})"
        )

    st.markdown("#### بازخورد")
    with st.form(f"feedback_form_{record_id}", border=False):
        fb_cols = st.columns(len(_FEEDBACK_BUTTONS))
        pressed_label: str | None = None
        for column, (label_fa, label_en) in zip(fb_cols, _FEEDBACK_BUTTONS):
            if label_en not in FEEDBACK_LABELS:
                continue
            with column:
                if st.form_submit_button(label_fa, use_container_width=True):
                    pressed_label = label_en
        comment = st.text_input("توضیح (اختیاری)")
        if pressed_label:
            _save_feedback(record_id, pressed_label, comment)
            st.success("بازخورد ذخیره شد.")
            st.rerun()


def _render_detail(record: dict[str, Any]) -> None:
    record_id = str(record["record_id"])
    pipeline = record.get("pipeline", {})
    status = str(record.get("status", ""))

    _render_room_summary(record)
    _render_conversation_timeline(record)
    _render_ai_reply_card(record)
    _render_send_preview_card(record)
    _render_tools_section(record)
    _render_evidence_section(record)

    with st.expander("جزئیات فنی"):
        st.json(pipeline.get("entities", {}))

    _render_intent_feedback(record)

    if status == "pending_review":
        _render_feedback(record)

    st.markdown("#### اقدامات")
    fund_confirmed = True
    if record.get("room_type") == "fund":
        fund_confirmed = st.checkbox(
            "تیکت مالی بررسی شد",
            key=f"fund_confirm_{record_id}",
        )

    buttons_disabled = not fund_confirmed or not can_send(status)
    refer_key = f"refer_to_{record_id}"

    a1, a2, a3, a4, a5 = st.columns([1.2, 1.2, 1.2, 1.4, 0.8])
    with a1:
        if st.button(
            "ارسال پاسخ",
            disabled=buttons_disabled,
            key=f"action_reply_{record_id}",
            use_container_width=True,
            type="primary",
        ):
            new_status = _handle_send(record, "reply", st.session_state.get(refer_key, ""))
            if new_status:
                st.session_state[f"action_status_{record_id}"] = new_status
                _cached_records.clear()
                st.rerun()
    with a2:
        if st.button(
            "ارسال پیشنهاد",
            disabled=buttons_disabled,
            key=f"action_suggestion_{record_id}",
            use_container_width=True,
            type="primary",
        ):
            new_status = _handle_send(record, "suggestion", st.session_state.get(refer_key, ""))
            if new_status:
                st.session_state[f"action_status_{record_id}"] = new_status
                _cached_records.clear()
                st.rerun()
    with a3:
        if st.button(
            "ارسال هر دو",
            disabled=buttons_disabled,
            key=f"action_both_{record_id}",
            use_container_width=True,
            type="primary",
        ):
            new_status = _handle_send(record, "both", st.session_state.get(refer_key, ""))
            if new_status:
                st.session_state[f"action_status_{record_id}"] = new_status
                _cached_records.clear()
                st.rerun()
    with a4:
        st.text_input("ارجاع", key=refer_key, placeholder="شناسه پیام")
    with a5:
        if st.button(
            "رد",
            disabled=not can_send(status),
            key=f"action_reject_{record_id}",
            use_container_width=True,
        ):
            new_status = _handle_send(record, "reject", st.session_state.get(refer_key, ""))
            if new_status:
                st.session_state[f"action_status_{record_id}"] = new_status
                _cached_records.clear()
                st.rerun()

    if status in {"send_failed", "error"}:
        if st.button("تلاش مجدد", key=f"retry_{record_id}"):
            st.session_state[f"retry_action_{record_id}"] = "reply"
            new_status = _handle_send(record, "retry", st.session_state.get(refer_key, ""))
            if new_status:
                st.session_state[f"action_status_{record_id}"] = new_status
                _cached_records.clear()
                st.rerun()

    action_status = st.session_state.get(f"action_status_{record_id}")
    if action_status:
        st.caption(f"نتیجه آخرین اقدام: {_status_label(str(action_status))}")

    if record.get("send_log"):
        with st.expander("گزارش ارسال"):
            st.json(record.get("send_log"))


def _ensure_selected_record(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    selected_id = st.session_state.get("selected_record_id")
    by_id = {str(record.get("record_id")): record for record in records}
    if selected_id in by_id:
        return by_id[selected_id]
    first = records[0]
    st.session_state.selected_record_id = str(first.get("record_id"))
    return first


def main() -> None:
    st.set_page_config(layout="wide", page_title="Inchand HITL Review")
    _inject_global_css()
    st.title("Live HITL Review Console")

    state_path = str(Path("state") / "hitl_state.jsonl")
    records = _cached_records(state_path)
    metrics = compute_metrics(records)
    _render_sidebar_metrics(metrics)

    filtered = sort_queue_records(_filter_records(records))

    if not filtered:
        st.info("هنوز رکوردی برای بررسی وجود ندارد.")
        return

    queue_col, detail_col = st.columns([1.1, 2.1], gap="small")
    with queue_col:
        _render_queue_table(filtered)
    with detail_col:
        selected = _ensure_selected_record(filtered)
        if selected:
            _render_detail(selected)

    if st.session_state.get("auto_refresh_toggle", True):
        if "last_refresh" not in st.session_state:
            st.session_state.last_refresh = time.time()
        if time.time() - st.session_state.last_refresh >= 10:
            st.session_state.last_refresh = time.time()
            _cached_records.clear()
            st.rerun()


if __name__ == "__main__":
    main()
