import pytest

from app.config import settings
from app.pipeline.evaluate_real_tickets import (
    _case_overall_pass,
    run_evaluation,
)
from app.pipeline.pipeline_eval_cases import KNOWN_CASE_COUNT, VARIATION_CASE_COUNT
from app.reply.templates import FORBIDDEN_ONBOARDING_PHRASES


@pytest.fixture(autouse=True)
def force_rule_provider(monkeypatch):
    monkeypatch.setattr(settings, "intent_classifier_provider", "rule")


def test_pipeline_real_ticket_evaluation_thresholds() -> None:
    results = run_evaluation()

    known = [item for item in results if "_variation_" not in item.case_id]
    variations = [item for item in results if "_variation_" in item.case_id]

    known_pass_count = sum(1 for item in known if _case_overall_pass(item))
    variation_pass_count = sum(1 for item in variations if _case_overall_pass(item))

    assert known_pass_count >= KNOWN_CASE_COUNT, [
        (item.case_id, item.issues) for item in known if not _case_overall_pass(item)
    ]
    assert variation_pass_count >= 7, [
        (item.case_id, item.issues) for item in variations if not _case_overall_pass(item)
    ]

    for item in results:
        for phrase in FORBIDDEN_ONBOARDING_PHRASES:
            assert phrase not in item.final_reply, item.case_id
