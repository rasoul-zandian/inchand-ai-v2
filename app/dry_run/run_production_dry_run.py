"""Production dry-run harness: pipeline evaluation without message delivery."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from app.integrations.inchand_poller_adapter import (
    build_pipeline_request_from_inchand_message,
)
from app.models.messages import ConversationMessage
from app.pipeline.run_pipeline import emit_pipeline_log, run_pipeline

if TYPE_CHECKING:
    from app.models.pipeline import PipelineResult


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    return rows


def normalize_row_to_inchand(row: dict) -> tuple[dict, list | None]:
    if "seller_message" in row:
        message = {
            "id": row.get("target_message_id") or row.get("message_id"),
            "room_id": row.get("room_id"),
            "sender": "shop",
            "content": row["seller_message"],
            "room_type": row.get("room_type"),
        }
        if row.get("shop_id") is not None:
            message["shop_id"] = row["shop_id"]

        context: list[dict] = []
        for item in row.get("conversation_context") or []:
            role = str(item.get("role", ""))
            sender = "shop" if role == "seller" else "admin"
            context.append(
                {
                    "id": item.get("message_id"),
                    "sender": sender,
                    "content": item.get("content", ""),
                }
            )
        return message, context or None

    message = {key: value for key, value in row.items() if key != "conversation_context"}
    context = row.get("conversation_context")
    return message, context


def capture_pipeline_result(
    result: PipelineResult,
    pipeline_request: dict,
) -> dict:
    send_gated = result.needs_human_review
    should_send = not result.needs_human_review
    final_reply_source = (
        "send_gate" if send_gated else result.final_reply.source
    )
    metadata = pipeline_request.get("metadata") or {}
    order_lookup = result.order_lookup_result
    tool_result = order_lookup.tool_result
    order_lookup_success = None
    if order_lookup.executed and tool_result is not None:
        order_lookup_success = tool_result.success

    return {
        "message_id": metadata.get("message_id"),
        "room_id": metadata.get("room_id"),
        "room_type": pipeline_request.get("room_type"),
        "primary_intent": result.intent_result.primary_intent.value,
        "confidence": result.intent_result.confidence,
        "suggested_action": result.intent_result.suggested_action.value,
        "needs_human_review": result.needs_human_review,
        "should_send": should_send,
        "selected_tools": list(result.tool_selection_result.selected_tools),
        "order_lookup_executed": order_lookup.executed,
        "order_lookup_success": order_lookup_success,
        "send_gated": send_gated,
        "final_reply_source": final_reply_source,
        "warnings": list(result.final_reply.warnings),
    }


def aggregate_results(results: list[dict], skipped: int) -> dict:
    total = len(results)
    auto_reply_count = sum(1 for item in results if item["should_send"])
    human_review_count = sum(1 for item in results if item["needs_human_review"])
    send_gated_count = sum(1 for item in results if item["send_gated"])
    order_lookup_count = sum(1 for item in results if item["order_lookup_executed"])

    intent_distribution = dict(Counter(item["primary_intent"] for item in results))
    suggested_action_distribution = dict(
        Counter(item["suggested_action"] for item in results)
    )
    room_type_distribution = dict(
        Counter(str(item["room_type"]) for item in results if item.get("room_type"))
    )

    tool_counter: Counter[str] = Counter()
    for item in results:
        for tool in item["selected_tools"]:
            tool_counter[tool] += 1
    tool_distribution = dict(tool_counter)

    warning_counter: Counter[str] = Counter()
    for item in results:
        for warning in item["warnings"]:
            warning_counter[warning] += 1
    top_warnings = [
        {"warning": warning, "count": count}
        for warning, count in warning_counter.most_common(10)
    ]

    return {
        "total_messages": total,
        "skipped_messages": skipped,
        "auto_reply_count": auto_reply_count,
        "human_review_count": human_review_count,
        "send_gated_count": send_gated_count,
        "human_review_pct": (human_review_count / total) if total else 0.0,
        "order_lookup_usage_pct": (order_lookup_count / total) if total else 0.0,
        "intent_distribution": intent_distribution,
        "suggested_action_distribution": suggested_action_distribution,
        "tool_distribution": tool_distribution,
        "room_type_distribution": room_type_distribution,
        "top_warnings": top_warnings,
        "results": [
            {key: value for key, value in item.items() if key != "warnings"}
            for item in results
        ],
    }


def build_markdown_summary(summary: dict, source_path: Path) -> str:
    total = summary["total_messages"]
    lines = [
        "# Dry Run Summary",
        "",
        f"Source: `{source_path}`",
        "",
        "## Messages processed",
        "",
        f"- Total: {total}",
        f"- Skipped: {summary['skipped_messages']}",
        f"- Auto reply: {summary['auto_reply_count']}",
        f"- Human review: {summary['human_review_count']}",
        f"- Send gated: {summary['send_gated_count']}",
        "",
        "## Intent distribution",
        "",
    ]
    for intent, count in sorted(summary["intent_distribution"].items()):
        lines.append(f"- {intent}: {count}")

    lines.extend(["", "## Suggested action distribution", ""])
    for action, count in sorted(summary["suggested_action_distribution"].items()):
        lines.append(f"- {action}: {count}")

    lines.extend(
        [
            "",
            "## Human review %",
            "",
            f"{summary['human_review_pct']:.1%}",
            "",
            "## Order lookup usage %",
            "",
            f"{summary['order_lookup_usage_pct']:.1%}",
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


def run_dry_run(input_path: Path, output_dir: Path) -> dict:
    rows = load_jsonl(input_path)
    results: list[dict] = []
    skipped = 0

    original_emit = emit_pipeline_log
    try:
        import app.pipeline.run_pipeline as run_pipeline_module

        run_pipeline_module.emit_pipeline_log = lambda _record: None

        for row in rows:
            inchand_message, inchand_context = normalize_row_to_inchand(row)
            try:
                pipeline_request = build_pipeline_request_from_inchand_message(
                    inchand_message,
                    conversation_context=inchand_context,
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
            results.append(capture_pipeline_result(pipeline_result, pipeline_request))
    finally:
        import app.pipeline.run_pipeline as run_pipeline_module

        run_pipeline_module.emit_pipeline_log = original_emit

    summary = aggregate_results(results, skipped)
    summary["source_path"] = str(input_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "dry_run_summary.json"
    md_path = output_dir / "dry_run_summary.md"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(
        build_markdown_summary(summary, input_path),
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(
            "Usage: python -m app.dry_run.run_production_dry_run <messages.jsonl> [output_dir]",
            file=sys.stderr,
        )
        return 2

    input_path = Path(args[0])
    output_dir = Path(args[1]) if len(args) > 1 else Path("reports")

    if not input_path.is_file():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    summary = run_dry_run(input_path, output_dir)
    print(f"total_messages: {summary['total_messages']}")
    print(f"skipped_messages: {summary['skipped_messages']}")
    print(f"auto_reply_count: {summary['auto_reply_count']}")
    print(f"human_review_count: {summary['human_review_count']}")
    print(f"send_gated_count: {summary['send_gated_count']}")
    print(f"reports written to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
