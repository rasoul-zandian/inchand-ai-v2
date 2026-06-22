import json

import pytest

from app.shadow.run_shadow_pilot import (
    aggregate_pilot_summaries,
    detect_daily_anomalies,
    write_pilot_summary,
)


def _day_summary(
    *,
    day: int,
    processed: int = 100,
    auto_reply: int = 50,
    human_review: int = 50,
    lookup_success: int = 98,
    lookup_failure: int = 2,
    escalate: int = 2,
    warnings: list[dict] | None = None,
) -> dict:
    return {
        "pilot_day": day,
        "day_label": f"day_{day:02d}",
        "total_rooms": processed,
        "processed_rooms": processed,
        "skipped_rooms": 0,
        "auto_reply_count": auto_reply,
        "human_review_count": human_review,
        "send_gated_count": human_review,
        "room_type_distribution": {"support": processed // 2, "complaint": processed // 2},
        "intent_distribution": {"general_inquiry": 40, "complaint_order_followup": 30},
        "suggested_action_distribution": {
            "reply_to_seller": auto_reply,
            "human_followup": human_review - escalate,
            "escalate": escalate,
        },
        "tool_usage_distribution": {"order_lookup": lookup_success + lookup_failure},
        "order_lookup_success_count": lookup_success,
        "order_lookup_failure_count": lookup_failure,
        "top_warnings": warnings or [{"warning": "order_lookup_failed", "count": lookup_failure}],
    }


def test_detect_daily_anomalies_flags_thresholds() -> None:
    summary = _day_summary(
        day=1,
        processed=100,
        auto_reply=10,
        human_review=90,
        lookup_success=90,
        lookup_failure=10,
    )

    flags = detect_daily_anomalies(summary, known_warnings=set())

    assert "order_lookup_success_below_95pct" in flags
    assert "human_review_above_80pct" in flags
    assert "auto_reply_below_20pct" in flags


def test_detect_daily_anomalies_flags_new_warning_type() -> None:
    summary = _day_summary(day=1, warnings=[{"warning": "new_signal", "count": 3}])

    flags = detect_daily_anomalies(summary, known_warnings={"order_lookup_failed"})

    assert any(flag.startswith("new_warning_types:") for flag in flags)


def test_aggregate_pilot_summaries(tmp_path) -> None:
    day_one = tmp_path / "day_01"
    day_two = tmp_path / "day_02"
    day_one.mkdir(parents=True)
    day_two.mkdir(parents=True)
    (day_one / "shadow_mode_summary.json").write_text(
        json.dumps(_day_summary(day=1), ensure_ascii=False),
        encoding="utf-8",
    )
    (day_two / "shadow_mode_summary.json").write_text(
        json.dumps(_day_summary(day=2, processed=80, auto_reply=40, human_review=40), ensure_ascii=False),
        encoding="utf-8",
    )

    pilot = aggregate_pilot_summaries(tmp_path)

    assert pilot["pilot_days"] == 2
    assert pilot["processed_rooms"] == 180
    assert pilot["auto_reply_count"] == 90
    assert pilot["human_review_count"] == 90
    assert len(pilot["daily_records"]) == 2
    assert pilot["order_lookup_success_pct"] == 0.98


def test_write_pilot_summary(tmp_path) -> None:
    day_dir = tmp_path / "day_01"
    day_dir.mkdir(parents=True)
    (day_dir / "shadow_mode_summary.json").write_text(
        json.dumps(_day_summary(day=1), ensure_ascii=False),
        encoding="utf-8",
    )

    pilot = write_pilot_summary(tmp_path)

    assert (tmp_path / "pilot_summary.json").is_file()
    assert (tmp_path / "pilot_summary.md").is_file()
    assert pilot["recommendation"].startswith("B)")
