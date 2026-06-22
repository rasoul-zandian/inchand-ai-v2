import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dashboard"))

from loader import (
    load_jsonl,
    load_private_inputs,
    merge_shadow_with_private_inputs,
    normalize_row,
)


def test_load_jsonl_reads_valid_file(tmp_path) -> None:
    path = tmp_path / "data.jsonl"
    path.write_text(
        '{"room_id": "1"}\n\n{"room_id": "2"}\n',
        encoding="utf-8",
    )

    rows = load_jsonl(str(path))

    assert rows == [{"room_id": "1"}, {"room_id": "2"}]


def test_load_jsonl_returns_empty_for_missing_file(tmp_path) -> None:
    assert load_jsonl(str(tmp_path / "missing.jsonl")) == []


def test_load_jsonl_raises_for_invalid_json(tmp_path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"ok": true}\nnot-json\n', encoding="utf-8")

    with pytest.raises(ValueError, match="invalid JSON on line 2"):
        load_jsonl(str(path))


def test_private_merge_adds_seller_message() -> None:
    results = [{"room_id": "42", "primary_intent": "general_inquiry"}]
    private = {
        "42": {
            "room_id": "42",
            "seller_message": "سلام",
            "conversation_context": [{"role": "assistant", "content": "پاسخ"}],
        }
    }

    merged = merge_shadow_with_private_inputs(results, private)

    assert merged[0]["seller_message"] == "سلام"
    assert merged[0]["conversation_context"] == [{"role": "assistant", "content": "پاسخ"}]


def test_normalize_row_fills_missing_fields() -> None:
    row = normalize_row({"room_id": "1", "primary_intent": "general_inquiry"})

    assert row["room_id"] == "1"
    assert row["primary_intent"] == "general_inquiry"
    assert row["confidence"] == 0.0
    assert row["entities"] == {}
    assert row["selected_tools"] == []
    assert row["warnings"] == []
    assert row["final_reply"] == ""
    assert row["seller_message"] == ""
    assert row["conversation_context"] == []


def test_load_private_inputs_indexes_by_room_id(tmp_path) -> None:
    path = tmp_path / "private.jsonl"
    path.write_text(
        json.dumps({"room_id": "7", "seller_message": "test"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    indexed = load_private_inputs(str(path))

    assert indexed["7"]["seller_message"] == "test"
