import json

import pytest

from app.config import settings
from app.dry_run.run_production_dry_run import run_dry_run


@pytest.fixture(autouse=True)
def force_rule_provider(monkeypatch):
    monkeypatch.setattr(settings, "intent_classifier_provider", "rule")
    monkeypatch.setattr("app.pipeline.run_pipeline.emit_pipeline_log", lambda _record: None)


def test_dry_run_writes_reports(tmp_path) -> None:
    input_file = tmp_path / "messages.jsonl"
    input_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": 1,
                        "room_id": 10,
                        "sender": "shop",
                        "content": "سلام",
                        "room_type": "support",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "id": 2,
                        "room_id": 10,
                        "sender": "shop",
                        "content": "رمز عبورم کار نمیکنه و نمیتونم وارد پنل بشم",
                        "room_type": "support",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "reports"

    summary = run_dry_run(input_file, output_dir)

    assert summary["total_messages"] == 2
    assert summary["auto_reply_count"] == 1
    assert summary["human_review_count"] == 1
    assert summary["send_gated_count"] == 1
    assert (output_dir / "dry_run_summary.json").is_file()
    assert (output_dir / "dry_run_summary.md").is_file()

    payload = json.loads((output_dir / "dry_run_summary.json").read_text(encoding="utf-8"))
    assert "seller_message" not in json.dumps(payload, ensure_ascii=False)
    assert payload["results"][0]["message_id"] == "1"
    assert payload["results"][1]["needs_human_review"] is True

    markdown = (output_dir / "dry_run_summary.md").read_text(encoding="utf-8")
    assert "# Dry Run Summary" in markdown
    assert "## Intent distribution" in markdown
