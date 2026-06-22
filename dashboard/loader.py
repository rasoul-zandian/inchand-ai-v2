"""Load and normalize shadow-mode dashboard data."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_ROW_KEYS = {
    "room_id": "",
    "shop_id": "",
    "target_message_id": "",
    "room_type": "",
    "primary_intent": "",
    "confidence": 0.0,
    "suggested_action": "",
    "needs_human_review": False,
    "should_send": False,
    "send_gated": False,
    "entities": {},
    "selected_tools": [],
    "order_lookup_executed": False,
    "order_lookup_success": None,
    "final_reply_source": "",
    "final_reply": "",
    "warnings": [],
    "seller_message": "",
    "conversation_context": [],
}


def load_jsonl(path: str) -> list[dict]:
    file_path = Path(path)
    if not file_path.exists():
        return []

    rows: list[dict] = []
    for line_number, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rows.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on line {line_number}: {exc.msg}") from exc
    return rows


def load_shadow_results(path: str) -> list[dict]:
    return load_jsonl(path)


def load_private_inputs(path: str) -> dict[str, dict]:
    rows = load_jsonl(path)
    indexed: dict[str, dict] = {}
    for row in rows:
        room_id = row.get("room_id")
        if room_id is not None:
            indexed[str(room_id)] = row
    return indexed


def merge_shadow_with_private_inputs(
    results: list[dict],
    private_by_room_id: dict[str, dict],
) -> list[dict]:
    merged: list[dict] = []
    for row in results:
        item = dict(row)
        private = private_by_room_id.get(str(item.get("room_id", "")))
        if private:
            if private.get("seller_message"):
                item["seller_message"] = private["seller_message"]
            if private.get("conversation_context"):
                item["conversation_context"] = private["conversation_context"]
            if private.get("target_message_id") and not item.get("target_message_id"):
                item["target_message_id"] = str(private["target_message_id"])
        merged.append(item)
    return merged


def normalize_row(row: dict) -> dict:
    normalized = dict(DEFAULT_ROW_KEYS)
    normalized.update(row)
    if normalized["entities"] is None:
        normalized["entities"] = {}
    if normalized["selected_tools"] is None:
        normalized["selected_tools"] = []
    if normalized["warnings"] is None:
        normalized["warnings"] = []
    if normalized["conversation_context"] is None:
        normalized["conversation_context"] = []
    return normalized
