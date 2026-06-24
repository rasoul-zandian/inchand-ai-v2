from pathlib import Path

import pytest

from hitl.app import merge_intent_feedback
from hitl.state import append_record, get_record, load_records, update_record


def test_merge_intent_feedback_correct() -> None:
    feedback = merge_intent_feedback(
        {"label": "correct", "comment": "ok"},
        intent_correct=True,
    )

    assert feedback["intent_correct"] is True
    assert "correct_intent" not in feedback
    assert feedback["label"] == "correct"
    assert feedback["intent_feedback_at_jalali"]


def test_merge_intent_feedback_wrong_requires_correct_intent() -> None:
    with pytest.raises(ValueError, match="missing_correct_intent"):
        merge_intent_feedback(None, intent_correct=False)


def test_merge_intent_feedback_wrong_persists_correct_intent() -> None:
    feedback = merge_intent_feedback(
        None,
        intent_correct=False,
        correct_intent="complaint_order_followup",
    )

    assert feedback["intent_correct"] is False
    assert feedback["correct_intent"] == "complaint_order_followup"


def test_intent_feedback_persisted_in_state(tmp_path: Path) -> None:
    state_file = tmp_path / "hitl_state.jsonl"
    append_record(
        {
            "record_id": "1:100",
            "target_message_id": "100",
            "status": "sent",
            "pipeline": {"primary_intent": "general_inquiry"},
            "feedback": None,
        },
        path=state_file,
    )

    merged = merge_intent_feedback(
        get_record("1:100", path=state_file).get("feedback"),
        intent_correct=False,
        correct_intent="settlement_inquiry",
    )
    update_record("1:100", {"feedback": merged}, path=state_file)

    record = load_records(state_file)[0]
    assert record["feedback"]["intent_correct"] is False
    assert record["feedback"]["correct_intent"] == "settlement_inquiry"
