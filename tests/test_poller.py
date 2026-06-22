from pathlib import Path

from hitl.poller import process_messages, run_poll_once


def test_process_messages_creates_pending_review_records(tmp_path, monkeypatch) -> None:
    state_file = tmp_path / "hitl_state.jsonl"
    monkeypatch.setenv("HITL_STATE_DIR", str(tmp_path))

    messages = [
        {
            "id": 1001,
            "room_id": 2001,
            "shop_id": 3001,
            "sender": "shop",
            "content": "سلام",
            "room_type": "support",
        },
        {
            "id": 1002,
            "room_id": 2002,
            "shop_id": 3002,
            "sender": "admin",
            "content": "ignored",
        },
    ]

    def fake_pipeline(_request):
        return {
            "primary_intent": "general_inquiry",
            "confidence": 0.5,
            "final_reply": "reply",
            "final_reply_source": "template",
            "suggested_action": "reply_to_seller",
            "entities": {},
            "selected_tools": [],
            "evidence": [],
            "safe_tool_output": [],
            "warnings": [],
        }

    created = process_messages(messages, pipeline_fn=fake_pipeline)
    assert len(created) == 1
    assert created[0]["status"] == "pending_review"
    assert created[0]["target_message_id"] == "1001"


def test_run_poll_once_skips_when_lock_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HITL_STATE_DIR", str(tmp_path))
    lock = tmp_path / "poller.lock"
    lock.write_text("locked", encoding="utf-8")
    result = run_poll_once(fetch_fn=lambda _state: [])
    assert result["skipped"] is True
