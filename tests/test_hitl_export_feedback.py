import json
from pathlib import Path

from hitl.export_feedback_dataset import (
    build_feedback_dataset,
    build_feedback_dataset_row,
    build_feedback_export_summary,
    has_intent_feedback,
    write_feedback_dataset,
)
from hitl.state import append_record, load_records


def test_has_intent_feedback_filters_records() -> None:
    assert has_intent_feedback({"feedback": {"intent_correct": True}}) is True
    assert has_intent_feedback({"feedback": {"correct_intent": "general_inquiry"}}) is True
    assert has_intent_feedback({"feedback": {"label": "wrong_reply"}}) is False
    assert has_intent_feedback({}) is False


def test_build_feedback_dataset_row_shape() -> None:
    record = {
        "record_id": "1:100",
        "room_id": "1",
        "shop_id": "2",
        "room_type": "support",
        "target_message_id": "100",
        "seller_message": "سلام",
        "conversation_context": [{"role": "user", "content": "prev"}],
        "pipeline": {
            "primary_intent": "general_inquiry",
            "confidence": 0.85,
            "suggested_action": "reply_to_seller",
            "final_reply": "پاسخ",
            "selected_tools": ["order_lookup"],
            "warnings": ["low_confidence"],
        },
        "warnings": ["room_hydration_failed"],
        "feedback": {
            "intent_correct": False,
            "correct_intent": "settlement_inquiry",
            "label": "wrong_intent",
        },
    }

    row = build_feedback_dataset_row(record)

    assert row["record_id"] == "1:100"
    assert row["predicted_intent"] == "general_inquiry"
    assert row["intent_correct"] is False
    assert row["correct_intent"] == "settlement_inquiry"
    assert row["confidence"] == 0.85
    assert row["reply_feedback"] == "wrong_intent"
    assert row["tools_used"] == ["order_lookup"]
    assert "low_confidence" in row["warnings"]
    assert "room_hydration_failed" in row["warnings"]


def test_build_feedback_export_summary_counts(tmp_path: Path) -> None:
    state_file = tmp_path / "hitl_state.jsonl"
    append_record(
        {
            "record_id": "1:1",
            "room_type": "support",
            "pipeline": {"primary_intent": "general_inquiry"},
            "feedback": {"intent_correct": True},
        },
        path=state_file,
    )
    append_record(
        {
            "record_id": "1:2",
            "room_type": "complaint",
            "pipeline": {"primary_intent": "shipping_inquiry"},
            "feedback": {
                "intent_correct": False,
                "correct_intent": "complaint_order_followup",
            },
        },
        path=state_file,
    )
    append_record(
        {
            "record_id": "1:3",
            "pipeline": {"primary_intent": "x"},
            "feedback": {"label": "correct"},
        },
        path=state_file,
    )

    rows = build_feedback_dataset(load_records(state_file))
    summary = build_feedback_export_summary(rows)

    assert len(rows) == 2
    assert summary["total_labeled_records"] == 2
    assert summary["intent_correct_count"] == 1
    assert summary["intent_wrong_count"] == 1
    assert summary["correction_distribution"] == [
        {"name": "complaint_order_followup", "count": 1}
    ]
    assert summary["top_predicted_wrong_intents"] == [
        {"name": "shipping_inquiry", "count": 1}
    ]


def test_write_feedback_dataset(tmp_path: Path) -> None:
    state_file = tmp_path / "hitl_state.jsonl"
    reports_dir = tmp_path / "reports"
    append_record(
        {
            "record_id": "9:9",
            "room_type": "support",
            "seller_message": "test",
            "pipeline": {"primary_intent": "general_inquiry", "final_reply": "r"},
            "feedback": {"intent_correct": True},
        },
        path=state_file,
    )

    rows, summary = write_feedback_dataset(
        state_path=state_file,
        jsonl_path=reports_dir / "hitl_feedback_dataset.jsonl",
        md_path=reports_dir / "hitl_feedback_summary.md",
    )

    jsonl_rows = [
        json.loads(line)
        for line in (reports_dir / "hitl_feedback_dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    md_text = (reports_dir / "hitl_feedback_summary.md").read_text(encoding="utf-8")

    assert len(rows) == 1
    assert jsonl_rows[0]["intent_correct"] is True
    assert summary["intent_correct_count"] == 1
    assert "HITL Feedback Dataset Summary" in md_text
