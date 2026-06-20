import pytest

from app.config import settings
from app.intent.evaluate_real_tickets import is_live_eval_enabled, print_report, run_evaluation
from app.intent.real_ticket_cases import REAL_TICKET_CASES


@pytest.fixture(autouse=True)
def force_rule_provider(monkeypatch):
    if not is_live_eval_enabled():
        monkeypatch.setattr(settings, "intent_classifier_provider", "rule")


def test_real_ticket_intent_eval_rule_provider(capsys):
    results = run_evaluation()
    print_report(results)

    passed_count = sum(1 for item in results if item.passed)
    assert passed_count >= 7, (
        "Expected at least 7/8 real ticket cases to pass with rule provider. "
        f"Got {passed_count}/8."
    )

    case_8 = next(item for item in results if item.case_id == "case_8_complaint_return_followup")
    if not case_8.passed:
        assert case_8.taxonomy_gap_note is not None


@pytest.mark.skipif(
    not is_live_eval_enabled(),
    reason="Set RUN_LIVE_INTENT_EVAL=1 with OPENAI_API_KEY and INTENT_CLASSIFIER_PROVIDER=openai",
)
def test_real_ticket_intent_eval_live_openai():
    results = run_evaluation()
    passed_count = sum(1 for item in results if item.passed)
    assert passed_count >= 7
    assert len(results) == len(REAL_TICKET_CASES)
