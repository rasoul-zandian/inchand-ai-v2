"""Local Streamlit dashboard for reviewing shadow-mode outputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.loader import (
    load_jsonl,
    load_private_inputs,
    load_shadow_results,
    merge_shadow_with_private_inputs,
    normalize_row,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="V2 Shadow Review Dashboard")
    parser.add_argument(
        "--results",
        default="reports/shadow_mode_results.jsonl",
    )
    parser.add_argument(
        "--summary",
        default="reports/shadow_mode_summary.json",
    )
    parser.add_argument(
        "--private",
        default="reports/shadow_mode_inputs_private.jsonl",
    )
    return parser.parse_args(argv)


def _load_summary(path: str, rows: list[dict]) -> dict:
    summary_path = Path(path)
    if summary_path.exists():
        return json.loads(summary_path.read_text(encoding="utf-8"))

    processed = len(rows)
    executed = sum(1 for row in rows if row.get("order_lookup_executed"))
    success = sum(1 for row in rows if row.get("order_lookup_success") is True)
    return {
        "processed_rooms": processed,
        "auto_reply_count": sum(1 for row in rows if row.get("should_send")),
        "human_review_count": sum(1 for row in rows if row.get("needs_human_review")),
        "order_lookup_success_count": success,
        "order_lookup_executed": executed,
    }


def _filter_rows(rows: list[dict]) -> list[dict]:
    filtered = rows

    review_filter = st.sidebar.selectbox(
        "needs_human_review",
        ["All", "Yes", "No"],
    )
    if review_filter == "Yes":
        filtered = [row for row in filtered if row.get("needs_human_review")]
    elif review_filter == "No":
        filtered = [row for row in filtered if not row.get("needs_human_review")]

    room_types = sorted({str(row.get("room_type", "")) for row in filtered if row.get("room_type")})
    selected_room_types = st.sidebar.multiselect("room_type", room_types, default=room_types)
    if selected_room_types:
        filtered = [row for row in filtered if str(row.get("room_type", "")) in selected_room_types]

    intents = sorted({str(row.get("primary_intent", "")) for row in filtered if row.get("primary_intent")})
    selected_intents = st.sidebar.multiselect("primary_intent", intents, default=intents)
    if selected_intents:
        filtered = [row for row in filtered if str(row.get("primary_intent", "")) in selected_intents]

    actions = sorted(
        {str(row.get("suggested_action", "")) for row in filtered if row.get("suggested_action")}
    )
    selected_actions = st.sidebar.multiselect("suggested_action", actions, default=actions)
    if selected_actions:
        filtered = [
            row for row in filtered if str(row.get("suggested_action", "")) in selected_actions
        ]

    if st.sidebar.checkbox("warning_present"):
        filtered = [row for row in filtered if row.get("warnings")]

    lookup_filter = st.sidebar.selectbox(
        "order_lookup_executed",
        ["All", "Yes", "No"],
    )
    if lookup_filter == "Yes":
        filtered = [row for row in filtered if row.get("order_lookup_executed")]
    elif lookup_filter == "No":
        filtered = [row for row in filtered if not row.get("order_lookup_executed")]

    if st.sidebar.checkbox("general_inquiry_only"):
        filtered = [row for row in filtered if row.get("primary_intent") == "general_inquiry"]

    return filtered


def _table_dataframe(rows: list[dict]) -> pd.DataFrame:
    table_rows = []
    for row in rows:
        table_rows.append(
            {
                "room_id": row.get("room_id", ""),
                "shop_id": row.get("shop_id", ""),
                "room_type": row.get("room_type", ""),
                "primary_intent": row.get("primary_intent", ""),
                "confidence": row.get("confidence", 0.0),
                "suggested_action": row.get("suggested_action", ""),
                "should_send": row.get("should_send", False),
                "needs_human_review": row.get("needs_human_review", False),
                "order_lookup_executed": row.get("order_lookup_executed", False),
                "order_lookup_success": row.get("order_lookup_success"),
                "final_reply_source": row.get("final_reply_source", ""),
                "warning_count": len(row.get("warnings") or []),
            }
        )
    return pd.DataFrame(table_rows)


def _option_label(row: dict) -> str:
    return (
        f"{row.get('room_id', '')} | {row.get('primary_intent', '')} | "
        f"{row.get('suggested_action', '')} | {row.get('should_send', '')}"
    )


def _render_detail(row: dict) -> None:
    st.subheader("Detail")
    st.write(f"Room: {row.get('room_id', '')}")
    st.write(f"Shop: {row.get('shop_id', '')}")
    st.write(f"Target Message: {row.get('target_message_id', '')}")
    st.write(f"Intent: {row.get('primary_intent', '')} ({row.get('confidence', 0.0)})")
    st.write(f"Suggested action: {row.get('suggested_action', '')}")
    st.write(f"should_send: {row.get('should_send', False)}")
    st.write(f"needs_human_review: {row.get('needs_human_review', False)}")
    st.write(f"send_gated: {row.get('send_gated', False)}")
    st.write(f"Selected tools: {', '.join(row.get('selected_tools') or []) or 'none'}")
    st.write(
        "Order lookup: "
        f"executed={row.get('order_lookup_executed', False)} "
        f"success={row.get('order_lookup_success')}"
    )
    st.write("Entities")
    st.json(row.get("entities") or {})
    st.write("Warnings")
    warnings = row.get("warnings") or []
    st.write(", ".join(warnings) if warnings else "none")

    st.markdown("### Generated Reply")
    final_reply = row.get("final_reply")
    if final_reply:
        st.markdown(f'<div dir="rtl">{final_reply}</div>', unsafe_allow_html=True)
    else:
        st.warning(
            "final_reply not available — update shadow runner to include safe final_reply"
        )

    st.markdown("### Seller Message")
    seller_message = row.get("seller_message")
    if seller_message:
        st.markdown(f'<div dir="rtl">{seller_message}</div>', unsafe_allow_html=True)
    else:
        st.info("Not available in safe shadow results")

    st.markdown("### Conversation Context")
    context = row.get("conversation_context") or []
    if context:
        for item in context[-10:]:
            role = item.get("role", "unknown")
            content = item.get("content", "")
            st.markdown(f"**{role}**")
            st.markdown(f'<div dir="rtl">{content}</div>', unsafe_allow_html=True)
    else:
        st.info("Not available")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    st.set_page_config(page_title="V2 Shadow Review", layout="wide")
    st.title("V2 Shadow Review Dashboard")

    raw_results = load_shadow_results(args.results)
    private_inputs = load_private_inputs(args.private)
    merged = merge_shadow_with_private_inputs(raw_results, private_inputs)
    rows = [normalize_row(row) for row in merged]
    summary = _load_summary(args.summary, rows)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total rows", summary.get("processed_rooms", len(rows)))
    col2.metric("Auto reply", summary.get("auto_reply_count", 0))
    col3.metric("Human review", summary.get("human_review_count", 0))
    col4.metric("Order lookup success", summary.get("order_lookup_success_count", 0))

    filtered = _filter_rows(rows)
    st.subheader("Results")
    st.dataframe(_table_dataframe(filtered), use_container_width=True)

    if not filtered:
        st.info("No rows match the current filters.")
        return

    labels = [_option_label(row) for row in filtered]
    selected_label = st.selectbox("Select room to review", labels)
    selected_row = filtered[labels.index(selected_label)]
    _render_detail(selected_row)


main()
