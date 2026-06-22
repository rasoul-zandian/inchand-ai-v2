"""JSONL state storage for HITL review records."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ALLOWED_STATUSES = {
    "new",
    "processing",
    "pending_review",
    "send_attempted",
    "send_failed",
    "sent",
    "suggested",
    "sent_both",
    "rejected_local",
    "error",
}

SENDABLE_STATUSES = {"pending_review", "send_failed", "error"}

FEEDBACK_LABELS = {
    "correct",
    "wrong_intent",
    "wrong_reply",
    "missing_tool",
    "wrong_tool",
}


def state_dir() -> Path:
    return Path(os.getenv("HITL_STATE_DIR", "state"))


def hitl_state_path() -> Path:
    return state_dir() / "hitl_state.jsonl"


def poller_state_path() -> Path:
    return state_dir() / "poller_state.json"


def poller_lock_path() -> Path:
    return state_dir() / "poller.lock"


def ensure_state_dir() -> Path:
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def load_records(path: Path | None = None) -> list[dict[str, Any]]:
    file_path = path or hitl_state_path()
    if not file_path.exists():
        return []

    records: list[dict[str, Any]] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


def append_record(record: dict[str, Any], path: Path | None = None) -> None:
    ensure_state_dir()
    file_path = path or hitl_state_path()
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _rewrite_records(records: list[dict[str, Any]], path: Path) -> None:
    ensure_state_dir()
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def update_record(
    record_id: str,
    updates: dict[str, Any],
    path: Path | None = None,
) -> dict[str, Any] | None:
    file_path = path or hitl_state_path()
    records = load_records(file_path)
    updated: dict[str, Any] | None = None
    for index, record in enumerate(records):
        if record.get("record_id") == record_id:
            merged = {**record, **updates}
            records[index] = merged
            updated = merged
            break
    if updated is None:
        return None
    _rewrite_records(records, file_path)
    return updated


def exists_message(target_message_id: str, path: Path | None = None) -> bool:
    target = str(target_message_id)
    return any(
        str(record.get("target_message_id")) == target
        for record in load_records(path)
    )


def get_record(record_id: str, path: Path | None = None) -> dict[str, Any] | None:
    for record in load_records(path):
        if record.get("record_id") == record_id:
            return record
    return None


def load_poller_state(path: Path | None = None) -> dict[str, Any]:
    file_path = path or poller_state_path()
    if not file_path.exists():
        return {
            "cursor_type": os.getenv("HITL_CURSOR_TYPE", "after_message_id"),
            "cursor_value": None,
        }
    return json.loads(file_path.read_text(encoding="utf-8"))


def save_poller_state(state: dict[str, Any], path: Path | None = None) -> None:
    ensure_state_dir()
    file_path = path or poller_state_path()
    file_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def poller_lock_exists(path: Path | None = None) -> bool:
    return (path or poller_lock_path()).exists()


def acquire_poller_lock(path: Path | None = None) -> bool:
    lock_path = path or poller_lock_path()
    ensure_state_dir()
    if lock_path.exists():
        return False
    lock_path.write_text("locked", encoding="utf-8")
    return True


def release_poller_lock(path: Path | None = None) -> None:
    lock_path = path or poller_lock_path()
    if lock_path.exists():
        lock_path.unlink()


def can_send(status: str) -> bool:
    return status in SENDABLE_STATUSES


def compute_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    processed = len(records)
    pending = sum(1 for record in records if record.get("status") == "pending_review")
    sent = sum(1 for record in records if record.get("status") == "sent")
    suggested = sum(1 for record in records if record.get("status") == "suggested")
    rejected = sum(1 for record in records if record.get("status") == "rejected_local")

    actionable = [record for record in records if record.get("status") in {"sent", "suggested", "sent_both"}]
    approval_rate = (len(actionable) / processed) if processed else 0.0

    feedback_records = [record for record in records if record.get("feedback")]
    feedback_count = len(feedback_records)

    def _feedback_count(label: str) -> int:
        return sum(
            1
            for record in feedback_records
            if record.get("feedback", {}).get("label") == label
        )

    intent_counts: dict[str, int] = {}
    for record in records:
        intent = str(record.get("pipeline", {}).get("primary_intent", "unknown"))
        intent_counts[intent] = intent_counts.get(intent, 0) + 1
    top_intents = sorted(intent_counts.items(), key=lambda item: item[1], reverse=True)[:5]

    return {
        "processed": processed,
        "pending": pending,
        "sent": sent,
        "suggested": suggested,
        "rejected": rejected,
        "approval_rate": round(approval_rate, 3),
        "feedback_count": feedback_count,
        "wrong_intent_count": _feedback_count("wrong_intent"),
        "wrong_reply_count": _feedback_count("wrong_reply"),
        "missing_tool_count": _feedback_count("missing_tool"),
        "wrong_tool_count": _feedback_count("wrong_tool"),
        "top_intents": top_intents,
    }
