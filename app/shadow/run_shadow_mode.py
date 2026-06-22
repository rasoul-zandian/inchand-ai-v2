"""Shadow mode: run V2 pipeline on room payloads without sending messages."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from app.integrations.inchand_poller_adapter import build_pipeline_request_from_inchand_room
from app.models.messages import ConversationMessage
from app.pipeline.run_pipeline import emit_pipeline_log, run_pipeline

if TYPE_CHECKING:
    from app.models.pipeline import PipelineResult

_SELLER_SENDERS = {"shop", "seller"}


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    return rows


def find_latest_seller_message_id(room: dict) -> str | None:
    messages = room.get("messages") or []
    latest_id = None
    for message in messages:
        sender = str(message.get("sender", ""))
        if sender in _SELLER_SENDERS and message.get("id") is not None:
            latest_id = str(message["id"])
    return latest_id


def extract_order_lookup_diagnostics(result: PipelineResult) -> dict | None:
    order_lookup = result.order_lookup_result
    if not order_lookup.executed or order_lookup.tool_result is None:
        return None

    tool_result = order_lookup.tool_result
    data = tool_result.data or {}
    diagnostics: dict[str, str | bool] = {}
    if tool_result.error is not None:
        diagnostics["order_lookup_error"] = tool_result.error
    if data.get("normalized_order_id"):
        diagnostics["normalized_order_id"] = str(data["normalized_order_id"])
    if tool_result.error == "missing_config":
        diagnostics["missing_config"] = True
    if data.get("http_status"):
        diagnostics["http_status"] = str(data["http_status"])
    if data.get("response_shape_summary"):
        diagnostics["response_shape_summary"] = str(data["response_shape_summary"])
    return diagnostics or None


def capture_shadow_result(
    result: PipelineResult,
    *,
    room_id: str,
    shop_id: str | None,
    target_message_id: str,
    room_type: str | None,
) -> dict:
    send_gated = result.needs_human_review
    should_send = not result.needs_human_review
    final_reply_source = (
        "send_gate" if send_gated else result.final_reply.source
    )
    order_lookup = result.order_lookup_result
    tool_result = order_lookup.tool_result
    order_lookup_success = None
    if order_lookup.executed and tool_result is not None:
        order_lookup_success = tool_result.success

    captured = {
        "room_id": room_id,
        "target_message_id": target_message_id,
        "primary_intent": result.intent_result.primary_intent.value,
        "confidence": result.intent_result.confidence,
        "suggested_action": result.intent_result.suggested_action.value,
        "needs_human_review": result.needs_human_review,
        "should_send": should_send,
        "send_gated": send_gated,
        "entities": dict(result.intent_result.entities),
        "selected_tools": list(result.tool_selection_result.selected_tools),
        "order_lookup_executed": order_lookup.executed,
        "order_lookup_success": order_lookup_success,
        "final_reply_source": final_reply_source,
        "warnings": list(result.final_reply.warnings),
    }
    if shop_id is not None:
        captured["shop_id"] = shop_id
    if room_type is not None:
        captured["room_type"] = room_type

    diagnostics = extract_order_lookup_diagnostics(result)
    if diagnostics:
        captured["order_lookup_diagnostics"] = diagnostics
    return captured


def aggregate_shadow_results(
    results: list[dict],
    *,
    total_rooms: int,
    skipped_rooms: int,
) -> dict:
    order_lookup_success_count = sum(
        1 for item in results if item.get("order_lookup_success") is True
    )
    order_lookup_failure_count = sum(
        1 for item in results if item.get("order_lookup_success") is False
    )

    tool_counter: Counter[str] = Counter()
    for item in results:
        for tool in item["selected_tools"]:
            tool_counter[tool] += 1

    warning_counter: Counter[str] = Counter()
    for item in results:
        for warning in item["warnings"]:
            warning_counter[warning] += 1

    failure_category_counter: Counter[str] = Counter()
    for item in results:
        if item.get("order_lookup_success") is not False:
            continue
        diagnostics = item.get("order_lookup_diagnostics") or {}
        error = diagnostics.get("order_lookup_error")
        if error:
            failure_category_counter[str(error)] += 1

    return {
        "total_rooms": total_rooms,
        "processed_rooms": len(results),
        "skipped_rooms": skipped_rooms,
        "auto_reply_count": sum(1 for item in results if item["should_send"]),
        "human_review_count": sum(1 for item in results if item["needs_human_review"]),
        "send_gated_count": sum(1 for item in results if item["send_gated"]),
        "room_type_distribution": dict(
            Counter(str(item["room_type"]) for item in results if item.get("room_type"))
        ),
        "intent_distribution": dict(
            Counter(item["primary_intent"] for item in results)
        ),
        "suggested_action_distribution": dict(
            Counter(item["suggested_action"] for item in results)
        ),
        "tool_usage_distribution": dict(tool_counter),
        "order_lookup_success_count": order_lookup_success_count,
        "order_lookup_failure_count": order_lookup_failure_count,
        "order_lookup_failure_categories": dict(failure_category_counter),
        "top_warnings": [
            {"warning": warning, "count": count}
            for warning, count in warning_counter.most_common(10)
        ],
    }


def build_markdown_summary(summary: dict, source_path: Path) -> str:
    lines = [
        "# Shadow Mode Summary",
        "",
        f"Source: `{source_path}`",
        "",
        f"- Total rooms: {summary['total_rooms']}",
        f"- Processed: {summary['processed_rooms']}",
        f"- Skipped: {summary['skipped_rooms']}",
        f"- Auto reply: {summary['auto_reply_count']}",
        f"- Human review: {summary['human_review_count']}",
        f"- Send gated: {summary['send_gated_count']}",
        "",
        "## Room type distribution",
        "",
    ]
    for room_type, count in sorted(summary["room_type_distribution"].items()):
        lines.append(f"- {room_type}: {count}")

    lines.extend(["", "## Intent distribution", ""])
    for intent, count in sorted(summary["intent_distribution"].items()):
        lines.append(f"- {intent}: {count}")

    lines.extend(["", "## Suggested action distribution", ""])
    for action, count in sorted(summary["suggested_action_distribution"].items()):
        lines.append(f"- {action}: {count}")

    lines.extend(["", "## Tool usage distribution", ""])
    if summary["tool_usage_distribution"]:
        for tool, count in sorted(summary["tool_usage_distribution"].items()):
            lines.append(f"- {tool}: {count}")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Order lookup",
            "",
            f"- Success: {summary['order_lookup_success_count']}",
            f"- Failure: {summary['order_lookup_failure_count']}",
            "",
            "## Order lookup failure categories",
            "",
        ]
    )
    failure_categories = summary.get("order_lookup_failure_categories") or {}
    if failure_categories:
        for category, count in sorted(failure_categories.items()):
            lines.append(f"- {category}: {count}")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Top warnings",
            "",
        ]
    )
    if summary["top_warnings"]:
        for item in summary["top_warnings"]:
            lines.append(f"- {item['warning']}: {item['count']}")
    else:
        lines.append("- none")

    return "\n".join(lines) + "\n"


def run_shadow_mode(input_path: Path, output_dir: Path) -> dict:
    rooms = load_jsonl(input_path)
    results: list[dict] = []
    skipped = 0

    original_emit = emit_pipeline_log
    try:
        import app.pipeline.run_pipeline as run_pipeline_module

        run_pipeline_module.emit_pipeline_log = lambda _record: None

        for room in rooms:
            target_message_id = find_latest_seller_message_id(room)
            if target_message_id is None:
                skipped += 1
                continue

            try:
                pipeline_request = build_pipeline_request_from_inchand_room(
                    room,
                    target_message_id,
                )
            except ValueError:
                skipped += 1
                continue

            context = None
            raw_context = pipeline_request.get("conversation_context")
            if raw_context:
                context = [ConversationMessage(**item) for item in raw_context]

            pipeline_result = run_pipeline(
                pipeline_request["seller_message"],
                conversation_context=context,
                room_type=pipeline_request.get("room_type"),
                metadata=pipeline_request.get("metadata"),
            )

            metadata = pipeline_request.get("metadata") or {}
            results.append(
                capture_shadow_result(
                    pipeline_result,
                    room_id=str(metadata.get("room_id", room.get("id"))),
                    shop_id=metadata.get("shop_id"),
                    target_message_id=target_message_id,
                    room_type=pipeline_request.get("room_type"),
                )
            )
    finally:
        import app.pipeline.run_pipeline as run_pipeline_module

        run_pipeline_module.emit_pipeline_log = original_emit

    summary = aggregate_shadow_results(
        results,
        total_rooms=len(rooms),
        skipped_rooms=skipped,
    )
    summary["source_path"] = str(input_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "shadow_mode_results.jsonl"
    summary_json_path = output_dir / "shadow_mode_summary.json"
    summary_md_path = output_dir / "shadow_mode_summary.md"

    with results_path.open("w", encoding="utf-8") as file:
        for item in results:
            file.write(json.dumps(item, ensure_ascii=False) + "\n")

    summary_json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_md_path.write_text(
        build_markdown_summary(summary, input_path),
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(
            "Usage: python -m app.shadow.run_shadow_mode <rooms.jsonl> [output_dir]",
            file=sys.stderr,
        )
        return 2

    input_path = Path(args[0])
    output_dir = Path(args[1]) if len(args) > 1 else Path("reports")

    if not input_path.is_file():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    summary = run_shadow_mode(input_path, output_dir)
    print(f"total_rooms: {summary['total_rooms']}")
    print(f"processed_rooms: {summary['processed_rooms']}")
    print(f"skipped_rooms: {summary['skipped_rooms']}")
    print(f"auto_reply_count: {summary['auto_reply_count']}")
    print(f"human_review_count: {summary['human_review_count']}")
    print(f"reports written to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
