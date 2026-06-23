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

import streamlit as st

from hitl.console_ui import format_time_label, render_console_html
from hitl.jalali import to_jalali
from hitl.sender import parse_refer_to, send_reply, send_suggestion
from hitl.state import can_send, compute_metrics, get_record, load_records, update_record

_SELLER_SENDERS = {"shop", "seller"}
_SUPPORT_SENDERS = {"admin", "support", "system"}
_TIMELINE_LABELS = {
    "seller": "فروشنده",
    "support": "پشتیبانی",
    "ai": "AI",
}

_NAV_FILTERS = {
    "all": None,
    "pending_review": {"pending_review"},
    "approved": {"sent", "sent_both", "suggested"},
    "needs_edit": {"send_failed", "error", "rejected_local"},
    "sent": {"sent", "sent_both", "suggested"},
}

_STREAMLIT_HIDE = """
<style>
#MainMenu, footer, header {visibility: hidden;}
.block-container {padding-top: 0.5rem; padding-bottom: 0.5rem; max-width: 100%;}
.stButton button {
  font-family: 'Tahoma','Segoe UI',Arial,sans-serif;
  font-size: 12px;
  border-radius: 8px;
}
</style>
"""


@st.cache_data(ttl=10)
def _cached_records(state_path: str) -> list[dict[str, Any]]:
    return load_records(Path(state_path))


def _classify_timeline_kind(item: dict[str, Any]) -> str:
    sender = str(item.get("sender", "")).lower()
    role = str(item.get("role", "")).lower()
    if sender in _SELLER_SENDERS or role == "user":
        return "seller"
    if sender in _SUPPORT_SENDERS or role == "assistant":
        return "support"
    return "support"


def _item_timestamp(item: dict[str, Any], fallback: str | None = None) -> str:
    for key in ("created_at_jalali", "timestamp", "created_at"):
        value = item.get(key)
        if value:
            text = str(value)
            if key == "created_at" and ("T" in text or text.endswith("Z")):
                try:
                    return to_jalali(text)
                except ValueError:
                    return text
            return text
    return fallback or ""


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
                    "label": _TIMELINE_LABELS[kind],
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
                    "timestamp": _item_timestamp(
                        {"created_at": record.get("created_at")},
                        str(record.get("created_at_jalali", "")),
                    ),
                    "is_target": True,
                    "sort_key": (1, int(target_id) if target_id.isdigit() else target_id),
                }
            )
        else:
            for message in timeline:
                if str(message["message_id"]) == target_id:
                    message["is_target"] = True

    return timeline


def _filter_records(records: list[dict[str, Any]], nav_key: str) -> list[dict[str, Any]]:
    allowed = _NAV_FILTERS.get(nav_key)
    if not allowed:
        return list(records)
    return [record for record in records if str(record.get("status", "")) in allowed]


def _handle_send(
    record: dict[str, Any],
    action: str,
    refer_to_raw: str,
    request_fn=None,
) -> None:
    record_id = str(record["record_id"])
    current = get_record(record_id)
    if current is None:
        st.error("Record not found.")
        return
    if action != "reject" and not can_send(str(current.get("status", ""))):
        st.error("Send blocked: record is not in a sendable status.")
        return

    try:
        refer_to = parse_refer_to(refer_to_raw)
    except ValueError:
        st.error("Refer To must be empty or a valid integer.")
        return

    if action == "reject":
        update_record(record_id, {"status": "rejected_local"})
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


def _init_state() -> None:
    defaults = {
        "hitl_nav": "pending_review",
        "hitl_tab": "conversation",
        "hitl_record_index": 0,
        "hitl_auto_refresh": True,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def main() -> None:
    st.set_page_config(layout="wide", page_title="Inchand HITL Review")
    _init_state()
    st.markdown(_STREAMLIT_HIDE, unsafe_allow_html=True)

    state_path = str(Path("state") / "hitl_state.jsonl")
    records = _cached_records(state_path)
    filtered = _filter_records(records, st.session_state.hitl_nav)
    filtered.sort(
        key=lambda record: (
            0 if record.get("status") == "pending_review" else 1,
            record.get("created_at_jalali", ""),
        ),
    )

    if not filtered:
        st.info("No review records yet.")
        return

    max_index = len(filtered) - 1
    if st.session_state.hitl_record_index > max_index:
        st.session_state.hitl_record_index = 0
    record = filtered[st.session_state.hitl_record_index]
    record_id = str(record["record_id"])
    timeline = build_timeline_messages(record)

    with st.sidebar:
        metrics = compute_metrics(records)
        st.header("Metrics")
        for key, value in metrics.items():
            if key != "top_intents":
                st.metric(key, value)
        st.write("Top intents", metrics.get("top_intents", []))
        st.session_state.hitl_auto_refresh = st.toggle(
            "Auto refresh (10s)",
            value=st.session_state.hitl_auto_refresh,
        )
        st.divider()
        st.subheader("Navigation")
        for nav_key, label in {
            "all": "همه موارد",
            "pending_review": "در انتظار بررسی",
            "approved": "تأیید شده",
            "needs_edit": "نیاز به ویرایش",
            "sent": "ارسال شده",
        }.items():
            if st.button(label, key=f"nav_{nav_key}", use_container_width=True):
                st.session_state.hitl_nav = nav_key
                st.session_state.hitl_record_index = 0
                st.rerun()
        st.caption(f"Record {st.session_state.hitl_record_index + 1}/{len(filtered)}")
        prev_col, next_col = st.columns(2)
        with prev_col:
            if st.button("◀ Prev", key="prev_record", use_container_width=True):
                if st.session_state.hitl_record_index > 0:
                    st.session_state.hitl_record_index -= 1
                    st.rerun()
        with next_col:
            if st.button("Next ▶", key="next_record", use_container_width=True):
                if st.session_state.hitl_record_index < max_index:
                    st.session_state.hitl_record_index += 1
                    st.rerun()
        st.divider()
        st.subheader("Tabs")
        for tab_id, label in [
            ("conversation", "مکالمه"),
            ("ai-reply", "پاسخ AI"),
            ("order", "جستجوی سفارش"),
            ("metadata", "متادیتا"),
        ]:
            if st.button(label, key=f"tab_{tab_id}", use_container_width=True):
                st.session_state.hitl_tab = tab_id
                st.rerun()
        st.divider()
        st.subheader("Actions")
        status = str(record.get("status", ""))
        fund_confirmed = True
        if record.get("room_type") == "fund":
            fund_confirmed = st.checkbox(
                "I reviewed this financial ticket.",
                key=f"fund_confirm_{record_id}",
            )
        refer_to_raw = st.text_input("Refer To (optional)", key=f"refer_to_{record_id}")
        buttons_disabled = not fund_confirmed or not can_send(status)
        if st.button("ارسال پاسخ", disabled=buttons_disabled, key=f"send_reply_{record_id}", use_container_width=True):
            _handle_send(record, "reply", refer_to_raw)
            st.rerun()
        if st.button("پیشنهاد ویرایش", disabled=buttons_disabled, key=f"send_suggestion_{record_id}", use_container_width=True):
            _handle_send(record, "suggestion", refer_to_raw)
            st.rerun()
        if st.button("رد کردن", disabled=not can_send(status), key=f"reject_{record_id}", use_container_width=True):
            _handle_send(record, "reject", refer_to_raw)
            st.rerun()

    st.markdown(
        render_console_html(
            record,
            records=records,
            timeline=timeline,
            active_tab=st.session_state.hitl_tab,
            active_nav=st.session_state.hitl_nav,
            last_update=format_time_label(),
            auto_refresh_on=st.session_state.hitl_auto_refresh,
        )
        + (
            "<script>window.setTimeout(function(){var el=document.getElementById('target-message-"
            + html.escape(str(record.get("target_message_id", "")), quote=True)
            + "');var box=document.getElementById('tab-conversation');"
            "if(el&&box){box.scrollTop=Math.max(0, el.offsetTop-box.offsetTop-80);}},120);</script>"
            if st.session_state.hitl_tab == "conversation"
            else ""
        ),
        unsafe_allow_html=True,
    )

    if st.session_state.hitl_auto_refresh:
        if "last_refresh" not in st.session_state:
            st.session_state.last_refresh = time.time()
        if time.time() - st.session_state.last_refresh >= 10:
            st.session_state.last_refresh = time.time()
            _cached_records.clear()
            st.rerun()


if __name__ == "__main__":
    main()
