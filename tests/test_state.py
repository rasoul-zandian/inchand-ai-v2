import json
from pathlib import Path

import pytest

from hitl.state import (
    append_record,
    compute_metrics,
    exists_message,
    load_records,
    update_record,
)


@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    return tmp_path / "hitl_state.jsonl"


def test_append_and_load(state_file: Path) -> None:
    record = {"record_id": "1:100", "target_message_id": "100", "status": "pending_review"}
    append_record(record, path=state_file)
    loaded = load_records(state_file)
    assert loaded == [record]


def test_update_record(state_file: Path) -> None:
    append_record({"record_id": "1:100", "target_message_id": "100", "status": "pending_review"}, state_file)
    updated = update_record("1:100", {"status": "sent"}, path=state_file)
    assert updated is not None
    assert updated["status"] == "sent"
    assert load_records(state_file)[0]["status"] == "sent"


def test_exists_message_dedup(state_file: Path) -> None:
    append_record({"record_id": "1:100", "target_message_id": "100"}, state_file)
    assert exists_message("100", path=state_file) is True
    assert exists_message("200", path=state_file) is False


def test_compute_metrics(state_file: Path) -> None:
    append_record(
        {
            "record_id": "1:1",
            "status": "pending_review",
            "pipeline": {"primary_intent": "shipping_inquiry"},
        },
        state_file,
    )
    append_record(
        {
            "record_id": "1:2",
            "status": "sent",
            "pipeline": {"primary_intent": "shipping_inquiry"},
            "feedback": {"label": "wrong_intent"},
        },
        state_file,
    )
    metrics = compute_metrics(load_records(state_file))
    assert metrics["processed"] == 2
    assert metrics["pending"] == 1
    assert metrics["sent"] == 1
    assert metrics["wrong_intent_count"] == 1
