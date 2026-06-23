"""Streamlit live HITL review console."""

from __future__ import annotations

import html
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd
import streamlit as st

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

_ROOM_TYPE_COLORS = {
    "complaint": "#fde2e2",
    "fund": "#fff3cd",
    "cancelation": "#e8f4ff",
    "support": "#e8f5e9",
}


@st.cache_data(ttl=10)
def _cached_records(state_path: str) -> list[dict[str, Any]]:
    return load_records(Path(state_path))


def _pipeline_field(record: dict[str, Any], key: str, default: str = "") -> str:
    return str(record.get("pipeline", {}).get(key, default))


def _table_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        pipeline = record.get("pipeline", {})
        rows.append(
            {
                "record_id": record.get("record_id"),
                "Time": record.get("created_at_jalali", ""),
                "Room": record.get("room_id", ""),
                "Shop": record.get("shop_id", ""),
                "Room Type": record.get("room_type", ""),
                "Intent": pipeline.get("primary_intent", ""),
                "Confidence": pipeline.get("confidence", ""),
                "Suggested Action": pipeline.get("suggested_action", ""),
                "Human Review": pipeline.get("needs_human_review", ""),
                "Tools": ", ".join(pipeline.get("selected_tools", [])),
                "Warning": ", ".join(record.get("warnings", [])),
                "Status": record.get("status", ""),
            }
        )
    return rows


def _filter_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered = records

    statuses = st.sidebar.multiselect(
        "status",
        sorted({str(record.get("status", "")) for record in records}),
        default=[],
    )
    if statuses:
        filtered = [record for record in filtered if record.get("status") in statuses]

    room_types = st.sidebar.multiselect(
        "room_type",
        sorted({str(record.get("room_type", "")) for record in records if record.get("room_type")}),
        default=[],
    )
    if room_types:
        filtered = [record for record in filtered if record.get("room_type") in room_types]

    intents = st.sidebar.multiselect(
        "intent",
        sorted(
            {
                str(record.get("pipeline", {}).get("primary_intent", ""))
                for record in records
                if record.get("pipeline", {}).get("primary_intent")
            }
        ),
        default=[],
    )
    if intents:
        filtered = [
            record
            for record in filtered
            if _pipeline_field(record, "primary_intent") in intents
        ]

    review_filter = st.sidebar.selectbox("needs_human_review", ["All", "Yes", "No"])
    if review_filter == "Yes":
        filtered = [
            record
            for record in filtered
            if record.get("pipeline", {}).get("needs_human_review") is True
        ]
    elif review_filter == "No":
        filtered = [
            record
            for record in filtered
            if record.get("pipeline", {}).get("needs_human_review") is not True
        ]

    tool_filter = st.sidebar.selectbox("tool usage", ["All", "order_lookup", "iran_post_tracking"])
    if tool_filter != "All":
        filtered = [
            record
            for record in filtered
            if tool_filter in record.get("pipeline", {}).get("selected_tools", [])
        ]

    return filtered


def _classify_timeline_kind(item: dict[str, Any]) -> str:
    sender = str(item.get("sender", "")).lower()
    role = str(item.get("role", "")).lower()
    if sender in _SELLER_SENDERS or role == "user":
        return "seller"
    if sender in _SUPPORT_SENDERS or role == "assistant":
        return "support"
    return "support"


def _item_timestamp(item: dict[str, Any], fallback: str | None = None) -> str | None:
    for key in ("timestamp", "created_at", "created_at_jalali"):
        value = item.get(key)
        if value:
            return str(value)
    return fallback


def _format_timeline_timestamp(value: str | None) -> str:
    if not value:
        return ""
    if any(ch in value for ch in "-/") and len(value) > 8:
        try:
            return to_jalali(value)
        except ValueError:
            return value
    return value


def build_timeline_messages(record: dict[str, Any]) -> list[dict[str, Any]]:
    target_id = str(record.get("target_message_id", ""))
    timeline: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for index, item in enumerate(record.get("conversation_context", [])):
        message_id = item.get("id")
        item_id = str(message_id) if message_id is not None else f"context-{index}"
        kind = _classify_timeline_kind(item)
        timeline.append(
            {
                "message_id": item_id,
                "kind": kind,
                "label": _TIMELINE_LABELS[kind],
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
                "timestamp": record.get("created_at"),
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
                "timestamp": record.get("created_at"),
                "is_target": False,
                "sort_key": (2, 0),
            }
        )

    return timeline


def _timeline_bubble_style(kind: str, is_target: bool) -> str:
    base = "margin: 8px 0; padding: 10px 12px; border-radius: 12px; max-width: 78%; line-height: 1.6;"
    if kind == "seller":
        style = (
            f"{base} margin-right: 0; margin-left: auto; background: #dbeafe; "
            "border: 1px solid #93c5fd; text-align: right;"
        )
    elif kind == "ai":
        style = (
            f"{base} margin-right: auto; margin-left: 0; background: #dcfce7; "
            "border: 1px solid #86efac; text-align: right;"
        )
    else:
        style = (
            f"{base} margin-right: auto; margin-left: 0; background: #f3f4f6; "
            "border: 1px solid #d1d5db; text-align: right;"
        )
    if is_target:
        style += " border: 2px solid #f59e0b !important; box-shadow: 0 0 0 1px #f59e0b33;"
    return style


def _render_conversation_timeline(record: dict[str, Any]) -> None:
    record_id = str(record.get("record_id", ""))
    messages = build_timeline_messages(record)
    target_id = str(record.get("target_message_id", ""))
    target_anchor = f"target-message-{html.escape(target_id, quote=True)}"

    st.markdown("### Conversation Timeline")
    if not messages:
        st.info("No conversation messages available for this record.")
        return

    header_html = (
        '<div style="display:flex; justify-content:space-between; align-items:center; '
        'margin-bottom:8px;">'
        f'<span style="color:#6b7280; font-size:13px;">{len(messages)} messages</span>'
        f'<a href="#{target_anchor}" style="text-decoration:none; background:#fff7ed; '
        'color:#b45309; border:1px solid #fdba74; border-radius:8px; padding:6px 10px; '
        'font-size:13px;">Go to current message</a>'
        "</div>"
    )
    st.markdown(header_html, unsafe_allow_html=True)

    parts = [
        '<div id="conversation-timeline" style="max-height:420px; overflow-y:auto; '
        'padding:12px; background:#fafafa; border:1px solid #e5e7eb; border-radius:12px;">'
    ]

    for message in messages:
        message_id = str(message["message_id"])
        anchor = (
            target_anchor
            if message.get("is_target")
            else f"timeline-message-{html.escape(message_id, quote=True)}"
        )
        timestamp = _format_timeline_timestamp(message.get("timestamp"))
        meta_bits = [html.escape(message["label"])]
        if timestamp:
            meta_bits.append(html.escape(timestamp))
        meta = " · ".join(meta_bits)
        badge = (
            '<span style="display:inline-block; margin-right:8px; background:#fef3c7; '
            'color:#92400e; border:1px solid #f59e0b; border-radius:999px; '
            'padding:2px 8px; font-size:11px;">پیام فعلی</span>'
            if message.get("is_target")
            else ""
        )
        content = html.escape(message.get("content", "")).replace("\n", "<br>")
        align = "flex-end" if message["kind"] == "seller" else "flex-start"
        parts.append(
            f'<div id="{anchor}" style="display:flex; justify-content:{align};">'
            f'<div style="{_timeline_bubble_style(message["kind"], bool(message.get("is_target")))}">'
            f'<div dir="rtl" style="font-size:12px; color:#4b5563; margin-bottom:6px;">'
            f"{badge}{meta}</div>"
            f'<div dir="rtl" style="font-size:15px; color:#111827;">{content}</div>'
            "</div></div>"
        )

    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)

    scroll_key = f"timeline_scrolled_{record_id}"
    if scroll_key not in st.session_state and target_id:
        st.session_state[scroll_key] = True
        st.markdown(
            f"<script>window.setTimeout(function(){{"
            f"var el=document.getElementById('{target_anchor}');"
            f"if(el){{el.scrollIntoView({{block:'center'}});"
            f"var box=document.getElementById('conversation-timeline');"
            f"if(box){{box.scrollTop=Math.max(0, el.offsetTop-box.offsetTop-80);}}}}"
            f"}}, 120);</script>",
            unsafe_allow_html=True,
        )


def _render_ai_reply_card(record: dict[str, Any]) -> None:
    pipeline = record.get("pipeline", {})
    final_reply = html.escape(str(pipeline.get("final_reply", ""))).replace("\n", "<br>")
    warnings = pipeline.get("warnings", []) or record.get("warnings", [])
    warning_text = html.escape(", ".join(str(item) for item in warnings)) or "—"

    st.markdown("### AI Reply")
    st.markdown(
        f"""
        <div style="background:#ffffff; border:1px solid #e5e7eb; border-radius:12px; padding:16px;">
          <div dir="rtl" style="font-size:16px; line-height:1.7; margin-bottom:14px;">{final_reply}</div>
          <div style="display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; font-size:14px;">
            <div><b>Intent</b><br>{html.escape(str(pipeline.get("primary_intent", "—")))}</div>
            <div><b>Confidence</b><br>{html.escape(str(pipeline.get("confidence", "—")))}</div>
            <div><b>Suggested Action</b><br>{html.escape(str(pipeline.get("suggested_action", "—")))}</div>
            <div><b>Should Send</b><br>{html.escape(str(pipeline.get("should_send", "—")))}</div>
            <div><b>Needs Human Review</b><br>{html.escape(str(pipeline.get("needs_human_review", "—")))}</div>
            <div><b>Source</b><br>{html.escape(str(pipeline.get("final_reply_source", "—")))}</div>
          </div>
          <div style="margin-top:12px; font-size:14px;"><b>Warnings</b><br>{warning_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _append_send_log(record: dict[str, Any], entry: dict[str, Any]) -> list[dict[str, Any]]:
    log = list(record.get("send_log", []))
    log.append(entry)
    return log


def _save_feedback(record_id: str, label: str, comment: str) -> None:
    update_record(
        record_id,
        {
            "feedback": {
                "label": label,
                "comment": comment,
                "created_at_jalali": to_jalali(),
            }
        },
    )


def _handle_send(
    record: dict[str, Any],
    action: str,
    refer_to_raw: str,
    request_fn=None,
) -> None:
    record_id = str(record["record_id"])
    current = get_record(record_id)
    if current is None or not can_send(str(current.get("status", ""))):
        st.error("Send blocked: record is not in a sendable status.")
        return

    try:
        refer_to = parse_refer_to(refer_to_raw)
    except ValueError:
        st.error("Refer To must be empty or a valid integer.")
        return

    update_record(record_id, {"status": "send_attempted"})
    logs = list(current.get("send_log", []))

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
        update_record(record_id, {"status": "rejected_local"})
    elif action == "retry":
        last_action = st.session_state.get(f"retry_action_{record_id}", "reply")
        _handle_send(record, last_action, refer_to_raw, request_fn=request_fn)
        return


def _render_detail(record: dict[str, Any]) -> None:
    record_id = str(record["record_id"])
    pipeline = record.get("pipeline", {})
    status = str(record.get("status", ""))

    st.subheader(f"Record {record_id}")
    st.caption(f"Status: {status} · Room {record.get('room_id', '')} · Shop {record.get('shop_id', '')}")

    _render_conversation_timeline(record)
    _render_ai_reply_card(record)

    with st.expander("Entities & Tool Output"):
        st.markdown("#### Entities")
        st.json(pipeline.get("entities", {}))
        st.markdown("#### Tool Output")
        st.json(record.get("tool_output", []))
        if pipeline.get("evidence"):
            st.markdown("#### Evidence")
            st.write(pipeline.get("evidence", []))

    if status == "pending_review":
        st.markdown("### AI Review Feedback")
        label = st.selectbox(
            "Feedback",
            ["", *sorted(FEEDBACK_LABELS)],
            key=f"feedback_label_{record_id}",
        )
        comment = st.text_input("Comment", key=f"feedback_comment_{record_id}")
        if st.button("Save Feedback", key=f"save_feedback_{record_id}"):
            if label:
                _save_feedback(record_id, label, comment)
                st.success("Feedback saved.")
                st.rerun()

    st.markdown("### Actions")
    fund_confirmed = True
    if record.get("room_type") == "fund":
        fund_confirmed = st.checkbox(
            "I reviewed this financial ticket.",
            key=f"fund_confirm_{record_id}",
        )

    refer_to_raw = st.text_input("Refer To (optional)", key=f"refer_to_{record_id}")
    buttons_disabled = not fund_confirmed or not can_send(status)

    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        if st.button("Send Reply", disabled=buttons_disabled, key=f"send_reply_{record_id}"):
            _handle_send(record, "reply", refer_to_raw)
            st.rerun()
    with col2:
        if st.button("Send Suggestion", disabled=buttons_disabled, key=f"send_suggestion_{record_id}"):
            _handle_send(record, "suggestion", refer_to_raw)
            st.rerun()
    with col3:
        if st.button("Send Both", disabled=buttons_disabled, key=f"send_both_{record_id}"):
            _handle_send(record, "both", refer_to_raw)
            st.rerun()
    with col4:
        if st.button("Reject", disabled=not can_send(status), key=f"reject_{record_id}"):
            _handle_send(record, "reject", refer_to_raw)
            st.rerun()
    with col5:
        if status in {"send_failed", "error"} and st.button("Retry", key=f"retry_{record_id}"):
            st.session_state[f"retry_action_{record_id}"] = "reply"
            _handle_send(record, "retry", refer_to_raw)
            st.rerun()

    if record.get("send_log"):
        st.markdown("### Send Log")
        st.json(record.get("send_log"))


def main() -> None:
    st.set_page_config(layout="wide", page_title="Inchand HITL Review")
    st.title("Live HITL Review Console")

    state_path = str(Path("state") / "hitl_state.jsonl")
    records = _cached_records(state_path)
    metrics = compute_metrics(records)

    st.sidebar.header("Metrics")
    for key, value in metrics.items():
        if key != "top_intents":
            st.sidebar.metric(key, value)
    st.sidebar.write("Top intents", metrics.get("top_intents", []))

    filtered = _filter_records(records)
    filtered.sort(
        key=lambda record: (
            0 if record.get("status") == "pending_review" else 1,
            record.get("created_at_jalali", ""),
        ),
    )

    rows = _table_rows(filtered)
    if rows:
        frame = pd.DataFrame(rows)
        st.dataframe(
            frame.drop(columns=["record_id"]),
            use_container_width=True,
            hide_index=True,
        )
        selected_index = st.number_input(
            "Select row index",
            min_value=0,
            max_value=max(0, len(filtered) - 1),
            value=0,
            step=1,
        )
        _render_detail(filtered[int(selected_index)])
    else:
        st.info("No review records yet.")

    if st.sidebar.toggle("Auto refresh (10s)", value=True):
        if "last_refresh" not in st.session_state:
            st.session_state.last_refresh = time.time()
        if time.time() - st.session_state.last_refresh >= 10:
            st.session_state.last_refresh = time.time()
            _cached_records.clear()
            st.rerun()


if __name__ == "__main__":
    main()
