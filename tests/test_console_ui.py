from hitl.app import _compute_sidebar_counts, _filter_by_nav, _record_feedback


def test_record_feedback_handles_null() -> None:
    record = {"record_id": "1:1", "feedback": None}
    assert _record_feedback(record) == {}


def test_sidebar_counts_with_null_feedback() -> None:
    records = [
        {"record_id": "1:1", "status": "pending_review", "feedback": None},
        {
            "record_id": "2:2",
            "status": "sent",
            "feedback": {"label": "correct", "comment": ""},
        },
        {
            "record_id": "3:3",
            "status": "pending_review",
            "feedback": {"label": "wrong_reply", "comment": "x"},
        },
    ]

    counts = _compute_sidebar_counts(records)

    assert counts["all"] == 3
    assert counts["pending"] == 2
    assert counts["approved"] == 1
    assert counts["needs_edit"] == 1
    assert _filter_by_nav(records, "approved")[0]["record_id"] == "2:2"
