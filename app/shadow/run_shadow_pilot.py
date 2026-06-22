"""7-day shadow pilot: daily runs, anomaly flags, cumulative reporting."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from app.shadow.run_shadow_mode import run_shadow_mode

PILOT_ROOT = Path("reports/pilot")
DAY_DIR_PATTERN = "day_{:02d}"


def day_dir(pilot_root: Path, day: int) -> Path:
    return pilot_root / DAY_DIR_PATTERN.format(day)


def run_pilot_day(
    day: int,
    rooms_file: Path,
    pilot_root: Path = PILOT_ROOT,
) -> dict:
    output_dir = day_dir(pilot_root, day)
    summary = run_shadow_mode(rooms_file, output_dir)
    summary["pilot_day"] = day
    summary["day_label"] = DAY_DIR_PATTERN.format(day)

    summary_json = output_dir / "shadow_mode_summary.json"
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    anomalies = detect_daily_anomalies(summary, known_warnings=set())
    if anomalies:
        (output_dir / "anomalies.json").write_text(
            json.dumps({"anomalies": anomalies}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return summary


def _merge_counter_dicts(items: list[dict[str, int]]) -> dict[str, int]:
    merged: Counter[str] = Counter()
    for item in items:
        merged.update(item)
    return dict(merged)


def _merge_warning_lists(items: list[list[dict]]) -> list[dict]:
    counter: Counter[str] = Counter()
    for warnings in items:
        for entry in warnings:
            counter[entry["warning"]] += entry["count"]
    return [{"warning": w, "count": c} for w, c in counter.most_common(10)]


def load_day_summaries(pilot_root: Path) -> list[dict]:
    summaries: list[dict] = []
    for path in sorted(pilot_root.glob("day_*/shadow_mode_summary.json")):
        summaries.append(json.loads(path.read_text(encoding="utf-8")))
    return summaries


def detect_daily_anomalies(
    summary: dict,
    *,
    known_warnings: set[str],
) -> list[str]:
    processed = summary.get("processed_rooms", 0)
    if processed == 0:
        return []

    flags: list[str] = []
    executed = (
        summary.get("order_lookup_success_count", 0)
        + summary.get("order_lookup_failure_count", 0)
    )
    if executed > 0:
        success_rate = summary.get("order_lookup_success_count", 0) / executed
        if success_rate < 0.95:
            flags.append("order_lookup_success_below_95pct")

    if summary.get("human_review_count", 0) / processed > 0.80:
        flags.append("human_review_above_80pct")

    if summary.get("auto_reply_count", 0) / processed < 0.20:
        flags.append("auto_reply_below_20pct")

    escalate = summary.get("suggested_action_distribution", {}).get("escalate", 0)
    if escalate / processed > 0.10:
        flags.append("escalate_above_10pct")

    day_warnings = {entry["warning"] for entry in summary.get("top_warnings", [])}
    new_warnings = day_warnings - known_warnings
    if new_warnings:
        flags.append(f"new_warning_types:{','.join(sorted(new_warnings))}")

    return flags


def aggregate_pilot_summaries(pilot_root: Path = PILOT_ROOT) -> dict:
    day_summaries = load_day_summaries(pilot_root)
    if not day_summaries:
        raise FileNotFoundError(f"No day summaries found under {pilot_root}")

    known_warnings: set[str] = set()
    daily_records: list[dict] = []
    for summary in day_summaries:
        anomalies = detect_daily_anomalies(summary, known_warnings=known_warnings)
        known_warnings.update(
            entry["warning"] for entry in summary.get("top_warnings", [])
        )
        processed = summary.get("processed_rooms", 0)
        executed = (
            summary.get("order_lookup_success_count", 0)
            + summary.get("order_lookup_failure_count", 0)
        )
        daily_records.append(
            {
                "day": summary.get("pilot_day"),
                "day_label": summary.get("day_label"),
                "processed_rooms": processed,
                "auto_reply_count": summary.get("auto_reply_count", 0),
                "human_review_count": summary.get("human_review_count", 0),
                "order_lookup_success_pct": (
                    summary.get("order_lookup_success_count", 0) / executed
                    if executed
                    else None
                ),
                "top_intents": sorted(
                    summary.get("intent_distribution", {}).items(),
                    key=lambda item: item[1],
                    reverse=True,
                )[:5],
                "anomalies": anomalies,
            }
        )

    total_processed = sum(item["processed_rooms"] for item in day_summaries)
    total_executed = sum(
        item.get("order_lookup_success_count", 0)
        + item.get("order_lookup_failure_count", 0)
        for item in day_summaries
    )

    pilot = {
        "pilot_days": len(day_summaries),
        "total_rooms": sum(item.get("total_rooms", 0) for item in day_summaries),
        "processed_rooms": total_processed,
        "skipped_rooms": sum(item.get("skipped_rooms", 0) for item in day_summaries),
        "auto_reply_count": sum(item.get("auto_reply_count", 0) for item in day_summaries),
        "human_review_count": sum(
            item.get("human_review_count", 0) for item in day_summaries
        ),
        "send_gated_count": sum(item.get("send_gated_count", 0) for item in day_summaries),
        "room_type_distribution": _merge_counter_dicts(
            [item.get("room_type_distribution", {}) for item in day_summaries]
        ),
        "intent_distribution": _merge_counter_dicts(
            [item.get("intent_distribution", {}) for item in day_summaries]
        ),
        "suggested_action_distribution": _merge_counter_dicts(
            [item.get("suggested_action_distribution", {}) for item in day_summaries]
        ),
        "tool_usage_distribution": _merge_counter_dicts(
            [item.get("tool_usage_distribution", {}) for item in day_summaries]
        ),
        "order_lookup_executed": total_executed,
        "order_lookup_success_count": sum(
            item.get("order_lookup_success_count", 0) for item in day_summaries
        ),
        "order_lookup_failure_count": sum(
            item.get("order_lookup_failure_count", 0) for item in day_summaries
        ),
        "order_lookup_success_pct": (
            sum(item.get("order_lookup_success_count", 0) for item in day_summaries)
            / total_executed
            if total_executed
            else None
        ),
        "top_warnings": _merge_warning_lists(
            [item.get("top_warnings", []) for item in day_summaries]
        ),
        "daily_records": daily_records,
        "daily_anomaly_count": sum(1 for record in daily_records if record["anomalies"]),
        "recommendation": _pilot_recommendation(day_summaries, daily_records),
        "opportunities": _pilot_opportunities(day_summaries),
    }
    return pilot


def _pilot_recommendation(day_summaries: list[dict], daily_records: list[dict]) -> str:
    total_executed = sum(
        item.get("order_lookup_success_count", 0)
        + item.get("order_lookup_failure_count", 0)
        for item in day_summaries
    )
    if total_executed > 0:
        success_rate = (
            sum(item.get("order_lookup_success_count", 0) for item in day_summaries)
            / total_executed
        )
        if success_rate < 0.90:
            return "C) Requires Architecture Changes"

    anomaly_days = sum(1 for record in daily_records if record["anomalies"])
    if anomaly_days > len(daily_records) // 2:
        return "B) Needs Additional Shadow Observation"

    total_processed = sum(item.get("processed_rooms", 0) for item in day_summaries)
    if total_processed == 0:
        return "B) Needs Additional Shadow Observation"

    human_review_pct = (
        sum(item.get("human_review_count", 0) for item in day_summaries) / total_processed
    )
    if human_review_pct > 0.85:
        return "B) Needs Additional Shadow Observation"

    if len(day_summaries) < 7:
        return "B) Needs Additional Shadow Observation"

    return "A) Ready for Limited Auto-Reply Pilot"


def _pilot_opportunities(day_summaries: list[dict]) -> dict:
    intents = _merge_counter_dicts(
        [item.get("intent_distribution", {}) for item in day_summaries]
    )
    tools = _merge_counter_dicts(
        [item.get("tool_usage_distribution", {}) for item in day_summaries]
    )
    warnings = _merge_warning_lists(
        [item.get("top_warnings", []) for item in day_summaries]
    )

    top_intents = sorted(intents.items(), key=lambda item: item[1], reverse=True)[:5]
    taxonomy_candidates = [
        intent
        for intent, count in top_intents
        if intent in {"general_inquiry"}
    ]
    tool_candidates = [tool for tool in tools if tool != "order_lookup"]
    reply_signals = [entry["warning"] for entry in warnings[:5]]

    return {
        "taxonomy_improvements": taxonomy_candidates,
        "new_tool_candidates": tool_candidates,
        "reply_improvements": reply_signals,
    }


def build_pilot_markdown(pilot: dict) -> str:
    lines = [
        "# Shadow Pilot Summary",
        "",
        f"- Pilot days: {pilot['pilot_days']}",
        f"- Processed rooms: {pilot['processed_rooms']}",
        f"- Auto reply: {pilot['auto_reply_count']}",
        f"- Human review: {pilot['human_review_count']}",
        f"- Send gated: {pilot['send_gated_count']}",
        "",
        "## Recommendation",
        "",
        pilot["recommendation"],
        "",
        "## Room types",
        "",
    ]
    for room_type, count in sorted(pilot["room_type_distribution"].items()):
        lines.append(f"- {room_type}: {count}")

    lines.extend(["", "## Suggested actions", ""])
    for action, count in sorted(pilot["suggested_action_distribution"].items()):
        lines.append(f"- {action}: {count}")

    lines.extend(["", "## Top intents", ""])
    for intent, count in sorted(
        pilot["intent_distribution"].items(),
        key=lambda item: item[1],
        reverse=True,
    )[:15]:
        lines.append(f"- {intent}: {count}")

    lookup_pct = pilot.get("order_lookup_success_pct")
    lines.extend(
        [
            "",
            "## Tool reliability",
            "",
            f"- Order lookup executed: {pilot['order_lookup_executed']}",
            f"- Success: {pilot['order_lookup_success_count']}",
            f"- Failure: {pilot['order_lookup_failure_count']}",
        ]
    )
    if lookup_pct is not None:
        lines.append(f"- Success rate: {lookup_pct:.1%}")

    lines.extend(["", "## Daily records", ""])
    for record in pilot["daily_records"]:
        lines.append(
            f"- {record['day_label']}: processed={record['processed_rooms']} "
            f"auto={record['auto_reply_count']} human={record['human_review_count']}"
        )
        if record["anomalies"]:
            lines.append(f"  - anomalies: {', '.join(record['anomalies'])}")

    lines.extend(["", "## Opportunities", ""])
    opportunities = pilot.get("opportunities", {})
    for key, values in opportunities.items():
        lines.append(f"- {key}: {', '.join(values) if values else 'none'}")

    return "\n".join(lines) + "\n"


def write_pilot_summary(pilot_root: Path = PILOT_ROOT) -> dict:
    pilot = aggregate_pilot_summaries(pilot_root)
    pilot_root.mkdir(parents=True, exist_ok=True)
    json_path = pilot_root / "pilot_summary.json"
    md_path = pilot_root / "pilot_summary.md"
    json_path.write_text(json.dumps(pilot, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(build_pilot_markdown(pilot), encoding="utf-8")
    return pilot


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(
            "Usage:\n"
            "  python -m app.shadow.run_shadow_pilot day <day_num> <rooms.jsonl>\n"
            "  python -m app.shadow.run_shadow_pilot aggregate",
            file=sys.stderr,
        )
        return 2

    command = args[0]
    if command == "day":
        if len(args) < 3:
            print("Usage: python -m app.shadow.run_shadow_pilot day <day_num> <rooms.jsonl>", file=sys.stderr)
            return 2
        day = int(args[1])
        rooms_file = Path(args[2])
        if not rooms_file.is_file():
            print(f"Input file not found: {rooms_file}", file=sys.stderr)
            return 1
        summary = run_pilot_day(day, rooms_file)
        print(f"pilot day {day:02d} complete")
        print(f"processed_rooms: {summary['processed_rooms']}")
        print(f"output: {day_dir(PILOT_ROOT, day)}")
        return 0

    if command == "aggregate":
        pilot = write_pilot_summary()
        print(f"pilot_days: {pilot['pilot_days']}")
        print(f"recommendation: {pilot['recommendation']}")
        print(f"summary: {PILOT_ROOT / 'pilot_summary.json'}")
        return 0

    print(f"Unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
