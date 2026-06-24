"""Export labeled HITL intent feedback for classifier training."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from hitl.state import hitl_state_path, load_records

_DEFAULT_JSONL_PATH = Path("reports/hitl_feedback_dataset.jsonl")
_DEFAULT_MD_PATH = Path("reports/hitl_feedback_summary.md")


def _count_distribution(values: list[str]) -> list[dict[str, Any]]:
    counts = Counter(values)
    return [
        {"name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def has_intent_feedback(record: dict[str, Any]) -> bool:
    feedback = record.get("feedback")
    if not isinstance(feedback, dict):
        return False
    if "intent_correct" in feedback:
        return True
    correct_intent = feedback.get("correct_intent")
    return bool(correct_intent is not None and str(correct_intent).strip())


def _record_tools(record: dict[str, Any]) -> list[str]:
    pipeline = record.get("pipeline", {})
    selected = pipeline.get("selected_tools")
    if not isinstance(selected, list):
        return []
    return [str(tool) for tool in selected if str(tool).strip()]


def _record_warnings(record: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for source in (record.get("warnings"), record.get("pipeline", {}).get("warnings")):
        if not isinstance(source, list):
            continue
        for item in source:
            text = str(item).strip()
            if text and text not in warnings:
                warnings.append(text)
    return warnings


def build_feedback_dataset_row(record: dict[str, Any]) -> dict[str, Any]:
    pipeline = record.get("pipeline", {})
    feedback = record.get("feedback", {})
    intent_correct = (
        feedback["intent_correct"] if "intent_correct" in feedback else None
    )
    correct_intent = feedback.get("correct_intent")
    reply_feedback = feedback.get("label")

    return {
        "record_id": record.get("record_id"),
        "room_id": record.get("room_id"),
        "shop_id": record.get("shop_id"),
        "room_type": record.get("room_type"),
        "target_message_id": record.get("target_message_id"),
        "seller_message": record.get("seller_message"),
        "conversation_context": list(record.get("conversation_context") or []),
        "predicted_intent": pipeline.get("primary_intent"),
        "intent_correct": intent_correct,
        "correct_intent": correct_intent,
        "confidence": pipeline.get("confidence"),
        "suggested_action": pipeline.get("suggested_action"),
        "final_reply": pipeline.get("final_reply"),
        "reply_feedback": reply_feedback,
        "tools_used": _record_tools(record),
        "warnings": _record_warnings(record),
    }


def build_feedback_dataset(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        build_feedback_dataset_row(record)
        for record in records
        if has_intent_feedback(record)
    ]


def build_feedback_export_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    intent_correct_count = sum(1 for row in rows if row.get("intent_correct") is True)
    intent_wrong_count = sum(1 for row in rows if row.get("intent_correct") is False)

    correction_names: list[str] = []
    predicted_wrong: list[str] = []
    room_types: list[str] = []
    for row in rows:
        room_type = str(row.get("room_type", "")).strip() or "unknown"
        room_types.append(room_type)
        if row.get("intent_correct") is False:
            predicted = str(row.get("predicted_intent", "")).strip() or "unknown"
            predicted_wrong.append(predicted)
            corrected = str(row.get("correct_intent", "")).strip()
            if corrected:
                correction_names.append(corrected)

    correction_distribution = _count_distribution(correction_names)
    examples_per_corrected_intent = list(correction_distribution)

    return {
        "total_labeled_records": len(rows),
        "intent_correct_count": intent_correct_count,
        "intent_wrong_count": intent_wrong_count,
        "correction_distribution": correction_distribution,
        "top_predicted_wrong_intents": _count_distribution(predicted_wrong)[:10],
        "room_type_distribution": _count_distribution(room_types),
        "examples_per_corrected_intent": examples_per_corrected_intent,
    }


def render_feedback_export_summary_md(summary: dict[str, Any]) -> str:
    lines = [
        "# HITL Feedback Dataset Summary",
        "",
        f"- Total labeled records: {summary['total_labeled_records']}",
        f"- Intent correct: {summary['intent_correct_count']}",
        f"- Intent wrong: {summary['intent_wrong_count']}",
        "",
        "## Correction distribution",
    ]
    if summary["correction_distribution"]:
        for item in summary["correction_distribution"]:
            lines.append(f"- {item['name']}: {item['count']}")
    else:
        lines.append("- —")

    lines.extend(["", "## Top predicted wrong intents"])
    if summary["top_predicted_wrong_intents"]:
        for item in summary["top_predicted_wrong_intents"]:
            lines.append(f"- {item['name']}: {item['count']}")
    else:
        lines.append("- —")

    lines.extend(["", "## Room types"])
    if summary["room_type_distribution"]:
        for item in summary["room_type_distribution"]:
            lines.append(f"- {item['name']}: {item['count']}")
    else:
        lines.append("- —")

    lines.extend(["", "## Examples per corrected intent"])
    if summary["examples_per_corrected_intent"]:
        for item in summary["examples_per_corrected_intent"]:
            lines.append(f"- {item['name']}: {item['count']}")
    else:
        lines.append("- —")

    lines.append("")
    return "\n".join(lines)


def write_feedback_dataset(
    *,
    state_path: Path | None = None,
    jsonl_path: Path | None = None,
    md_path: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = build_feedback_dataset(load_records(state_path))
    summary = build_feedback_export_summary(rows)

    output_jsonl = jsonl_path or _DEFAULT_JSONL_PATH
    output_md = md_path or _DEFAULT_MD_PATH
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)

    with output_jsonl.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    output_md.write_text(render_feedback_export_summary_md(summary), encoding="utf-8")
    return rows, summary


def main(argv: list[str] | None = None) -> int:
    _ = argv
    rows, _summary = write_feedback_dataset(state_path=hitl_state_path())
    print(f"Wrote {_DEFAULT_JSONL_PATH} ({len(rows)} rows)")
    print(f"Wrote {_DEFAULT_MD_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
