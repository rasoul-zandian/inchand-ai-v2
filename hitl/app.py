"""Streamlit live HITL review console."""

from __future__ import annotations

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
    st.caption(f"Status: {status}")

    st.markdown("### Seller Message")
    st.markdown(
        f'<div dir="rtl" style="text-align:right;">{record.get("seller_message", "")}</div>',
        unsafe_allow_html=True,
    )

    st.markdown("### Conversation Context")
    for item in record.get("conversation_context", [])[-10:]:
        role = item.get("role", "unknown")
        content = item.get("content", "")
        st.markdown(
            f'<div dir="rtl" style="text-align:right;"><b>{role}</b>: {content}</div>',
            unsafe_allow_html=True,
        )

    st.markdown("### Generated Reply")
    st.markdown(
        f'<div dir="rtl" style="text-align:right;">{pipeline.get("final_reply", "")}</div>',
        unsafe_allow_html=True,
    )
    st.write(f"Source: {pipeline.get('final_reply_source', '')}")

    st.markdown("### Classification")
    st.write(
        {
            "primary_intent": pipeline.get("primary_intent"),
            "confidence": pipeline.get("confidence"),
            "evidence": pipeline.get("evidence", []),
            "suggested_action": pipeline.get("suggested_action"),
        }
    )

    st.markdown("### Entities")
    st.json(pipeline.get("entities", {}))

    st.markdown("### Tool Output")
    st.json(record.get("tool_output", []))

    st.markdown("### Warnings")
    st.write(record.get("warnings", []))

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

    fund_confirmed = True
    if record.get("room_type") == "fund":
        fund_confirmed = st.checkbox(
            "I reviewed this financial ticket.",
            key=f"fund_confirm_{record_id}",
        )

    refer_to_raw = st.text_input("Refer To (optional)", key=f"refer_to_{record_id}")
    buttons_disabled = not fund_confirmed or not can_send(status)

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
