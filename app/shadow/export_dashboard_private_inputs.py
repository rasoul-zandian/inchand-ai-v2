"""Export private local inputs for the shadow review dashboard."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.integrations.inchand_poller_adapter import build_pipeline_request_from_inchand_room
from app.shadow.run_shadow_mode import find_latest_seller_message_id, load_jsonl

DEFAULT_OUTPUT = Path("reports/shadow_mode_inputs_private.jsonl")


def export_private_input_from_room(room: dict) -> dict | None:
    target_message_id = find_latest_seller_message_id(room)
    if target_message_id is None:
        return None

    try:
        pipeline_request = build_pipeline_request_from_inchand_room(room, target_message_id)
    except ValueError:
        return None

    metadata = pipeline_request.get("metadata") or {}
    row = {
        "room_id": str(metadata.get("room_id", room.get("id"))),
        "target_message_id": str(metadata.get("message_id", target_message_id)),
        "seller_message": pipeline_request["seller_message"],
    }
    context = pipeline_request.get("conversation_context")
    if context:
        row["conversation_context"] = context
    return row


def export_dashboard_private_inputs(
    input_path: Path,
    output_path: Path = DEFAULT_OUTPUT,
) -> int:
    rooms = load_jsonl(input_path)
    rows: list[dict] = []
    for room in rooms:
        row = export_private_input_from_room(room)
        if row is not None:
            rows.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(
            "Usage: python -m app.shadow.export_dashboard_private_inputs <rooms.jsonl> [output.jsonl]",
            file=sys.stderr,
        )
        return 2

    input_path = Path(args[0])
    output_path = Path(args[1]) if len(args) > 1 else DEFAULT_OUTPUT

    if not input_path.is_file():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    count = export_dashboard_private_inputs(input_path, output_path)
    print(f"rows_written: {count}")
    print(f"output: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
