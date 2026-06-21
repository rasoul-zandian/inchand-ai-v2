import pytest

from app.config import settings
from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult, SuggestedAction
from app.models.messages import ConversationMessage
from app.models.tool_contracts import ToolRequest, ToolResult
from app.pipeline.run_pipeline import run_pipeline
from app.tools.order_lookup import ORDER_LOOKUP_TOOL
from app.tools.selection import ORDER_LOOKUP

_HUMAN_REVIEW_ACKNOWLEDGEMENT = (
    "درخواست شما دریافت شد و جهت بررسی به کارشناسان مربوطه ارجاع شد."
)


@pytest.fixture(autouse=True)
def force_rule_provider(monkeypatch):
    monkeypatch.setattr(settings, "intent_classifier_provider", "rule")


def test_pipeline_passes_conversation_context_to_classifier(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_classify(message, conversation_context=None, room_type=None):
        captured["message"] = message
        captured["conversation_context"] = conversation_context
        captured["room_type"] = room_type
        return IntentClassificationResult(
            primary_intent=IntentId.GENERAL_INQUIRY,
            confidence=0.5,
            suggested_action=SuggestedAction.REPLY_TO_SELLER,
        )

    monkeypatch.setattr("app.pipeline.run_pipeline.classify_intent", fake_classify)

    context = [ConversationMessage(role="assistant", content="شکایت سفارش INC-7342409")]
    run_pipeline("تماس گرفته شد", conversation_context=context)

    assert captured["message"] == "تماس گرفته شد"
    assert captured["conversation_context"] == context
    assert captured["room_type"] is None


def test_pipeline_passes_room_type_to_classifier(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_classify(message, conversation_context=None, room_type=None):
        captured["room_type"] = room_type
        return IntentClassificationResult(
            primary_intent=IntentId.GENERAL_INQUIRY,
            confidence=0.5,
            suggested_action=SuggestedAction.REPLY_TO_SELLER,
        )

    monkeypatch.setattr("app.pipeline.run_pipeline.classify_intent", fake_classify)

    run_pipeline("لغو کنید", room_type="complaint")

    assert captured["room_type"] == "complaint"


def test_bank_account_change_pipeline_completes_with_final_reply() -> None:
    result = run_pipeline(
        "سلام وقت بخیر میخوام شماره حسابم رو لطفا تغییر بدین "
        "حساب فعلی من صادرات که میخوام سامان تغییر بدم"
    )

    assert result.intent_result.primary_intent == IntentId.BANK_ACCOUNT_CHANGE
    assert result.final_reply.text
    assert result.order_lookup_result.executed is False
    assert result.tool_selection_result.selected_tools == []


def test_product_approval_request_no_tool_selected() -> None:
    result = run_pipeline("لطفا محصولاتی که هنوز تایید نشده رو تایید می کنید")

    assert result.intent_result.primary_intent == IntentId.PRODUCT_APPROVAL_REQUEST
    assert result.tool_selection_result.selected_tools == []
    assert result.order_lookup_result.executed is False
    assert result.needs_human_review is True
    assert result.final_reply.text == _HUMAN_REVIEW_ACKNOWLEDGEMENT


def test_account_access_issue_send_gate() -> None:
    result = run_pipeline("رمز عبورم کار نمیکنه و نمیتونم وارد پنل بشم")

    assert result.intent_result.primary_intent == IntentId.ACCOUNT_ACCESS_ISSUE
    assert result.needs_human_review is True
    assert result.final_reply.text == _HUMAN_REVIEW_ACKNOWLEDGEMENT


def test_complaint_followup_send_gate() -> None:
    context = [
        ConversationMessage(
            role="assistant",
            content=(
                "فروشنده گرامی در مورد سفارش INC-7342409 شکایتی از فروشگاه شما ثبت شده است."
            ),
        ),
    ]
    result = run_pipeline(
        "تماس گرفته شد، قرار شد کالا برگشت داده شود",
        conversation_context=context,
    )

    assert result.intent_result.primary_intent == IntentId.COMPLAINT_ORDER_FOLLOWUP
    assert result.needs_human_review is True
    assert result.final_reply.text == _HUMAN_REVIEW_ACKNOWLEDGEMENT


def test_order_status_inquiry_preserves_enriched_reply(monkeypatch) -> None:
    intent = IntentClassificationResult(
        primary_intent=IntentId.ORDER_STATUS_INQUIRY,
        confidence=0.9,
        entities={"order_id": "INC-7342409"},
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )
    monkeypatch.setattr("app.pipeline.run_pipeline.classify_intent", lambda *_a, **_k: intent)

    def fake_lookup(request: ToolRequest) -> ToolResult:
        assert request.tool_name == ORDER_LOOKUP_TOOL
        return ToolResult(
            tool_name=ORDER_LOOKUP_TOOL,
            success=True,
            data={
                "order_id": "INC-7342409",
                "found": "true",
                "order_status": "ارسال شده",
                "primary_parcel_status_name": "تحویل پست",
                "primary_parcel_tracking_code": "9876543210",
                "has_parcel_tracking_code": "true",
                "is_delivered_in_inchand": "false",
            },
            summary="ok",
        )

    result = run_pipeline("سفارش INC-7342409 الان کجاست؟", lookup_fn=fake_lookup)

    assert result.needs_human_review is False
    assert ORDER_LOOKUP in result.tool_selection_result.selected_tools
    assert result.order_lookup_result.executed is True
    assert "وضعیت سفارش INC-7342409: ارسال شده." in result.final_reply.text
    assert "کد رهگیری: 9876543210." in result.final_reply.text


def test_delivered_order_final_reply(monkeypatch) -> None:
    intent = IntentClassificationResult(
        primary_intent=IntentId.ORDER_STATUS_INQUIRY,
        confidence=0.9,
        entities={"order_id": "INC-7342409"},
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )
    monkeypatch.setattr("app.pipeline.run_pipeline.classify_intent", lambda *_a, **_k: intent)

    def fake_lookup(_request: ToolRequest) -> ToolResult:
        return ToolResult(
            tool_name=ORDER_LOOKUP_TOOL,
            success=True,
            data={
                "order_id": "INC-7342409",
                "found": "true",
                "order_status": "تحویل شده",
                "is_delivered_in_inchand": "true",
                "primary_parcel_tracking_code": "9876543210",
                "has_parcel_tracking_code": "true",
            },
            summary="ok",
        )

    result = run_pipeline("وضعیت سفارش INC-7342409", lookup_fn=fake_lookup)

    assert result.needs_human_review is False
    assert (
        result.final_reply.text
        == "وضعیت سفارش INC-7342409 در وضعیت تحویل شده قرار دارد."
    )
