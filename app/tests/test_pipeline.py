import pytest

from app.config import settings
from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult, SuggestedAction
from app.models.messages import ConversationMessage
from app.models.pipeline import OrderLookupExecutionResult
from app.models.tool_contracts import ToolRequest, ToolResult
from app.pipeline.run_pipeline import run_pipeline
from app.reply.templates import DELIVERY_CONFIRMATION_MISSING_ORDER_ID_REPLY
from app.tools.order_lookup import ORDER_LOOKUP_TOOL
from app.tools.selection import ORDER_LOOKUP

_HUMAN_REVIEW_ACKNOWLEDGEMENT = (
    "درخواست شما دریافت شد و جهت بررسی به کارشناسان مربوطه ارجاع شد."
)


@pytest.fixture(autouse=True)
def force_rule_provider(monkeypatch):
    monkeypatch.setattr(settings, "intent_classifier_provider", "rule")
    monkeypatch.setattr("app.pipeline.run_pipeline.emit_pipeline_log", lambda _record: None)


def test_pipeline_passes_shop_id_to_tool_context(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_order_lookup(_tool_selection, _intent_result, context, lookup_fn=None):
        captured["context"] = context
        return OrderLookupExecutionResult(executed=False)

    monkeypatch.setattr(
        "app.pipeline.run_pipeline.run_selected_order_lookup",
        fake_order_lookup,
    )

    run_pipeline("سلام", metadata={"shop_id": "7304"})

    assert captured["context"]["shop_id"] == "7304"


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


def test_delivery_confirmation_without_order_id_asks_for_order_number(monkeypatch) -> None:
    intent = IntentClassificationResult(
        primary_intent=IntentId.DELIVERY_CONFIRMATION_REQUEST,
        confidence=0.9,
        entities={},
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )
    monkeypatch.setattr("app.pipeline.run_pipeline.classify_intent", lambda *_a, **_k: intent)

    lookup_called = False

    def fake_lookup(_request: ToolRequest) -> ToolResult:
        nonlocal lookup_called
        lookup_called = True
        return ToolResult(tool_name=ORDER_LOOKUP_TOOL, success=True, data={}, summary="ok")

    result = run_pipeline(
        "سلام خسته نباشید من دوهفته پیش یه بسته ارسال کردم دست مشتری رسیده",
        lookup_fn=fake_lookup,
    )

    assert result.intent_result.suggested_action == SuggestedAction.REQUEST_MISSING_INFORMATION
    assert result.final_reply.text == DELIVERY_CONFIRMATION_MISSING_ORDER_ID_REPLY
    assert result.final_reply.suggested_action == SuggestedAction.REQUEST_MISSING_INFORMATION
    assert result.needs_human_review is False
    assert ORDER_LOOKUP not in result.tool_selection_result.selected_tools
    assert result.order_lookup_result.executed is False
    assert lookup_called is False
    assert "missing_order_id_for_delivery_confirmation" in result.final_reply.warnings


def test_delivery_confirmation_pipeline_runs_order_lookup(monkeypatch) -> None:
    intent = IntentClassificationResult(
        primary_intent=IntentId.DELIVERY_CONFIRMATION_REQUEST,
        confidence=0.9,
        entities={"order_ids": ["INC-7338176", "INC-7337206"]},
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )
    monkeypatch.setattr("app.pipeline.run_pipeline.classify_intent", lambda *_a, **_k: intent)

    calls: list[ToolRequest] = []

    def fake_lookup(request: ToolRequest) -> ToolResult:
        calls.append(request)
        order_id = request.entities["order_id"]
        tracking = "9876543210" if order_id == "INC-7338176" else "8765432109"
        return ToolResult(
            tool_name=ORDER_LOOKUP_TOOL,
            success=True,
            data={
                "order_id": order_id,
                "found": "true",
                "order_status": "تحویل شده",
                "primary_parcel_status_name": "تحویل پست",
                "primary_parcel_tracking_code": tracking,
                "has_parcel_tracking_code": "true",
            },
            summary="ok",
        )

    result = run_pipeline(
        "سلام سفارش های INC-7338176 - INC-7337206 تحویل داده شدند",
        metadata={"shop_id": "5456"},
        lookup_fn=fake_lookup,
    )

    assert ORDER_LOOKUP in result.tool_selection_result.selected_tools
    assert result.order_lookup_result.executed is True
    assert len(calls) == 2
    assert all(call.context["shop_id"] == "5456" for call in calls)
    assert [call.entities["order_id"] for call in calls] == [
        "INC-7338176",
        "INC-7337206",
    ]
    assert "اطلاع شما درباره تحویل سفارش‌ها دریافت شد." in result.final_reply.text
    assert "وضعیت سفارش INC-7338176: تحویل شده." in result.final_reply.text
    assert "وضعیت سفارش INC-7337206: تحویل شده." in result.final_reply.text
    assert "کد رهگیری: 9876543210." in result.final_reply.text
    assert "کد رهگیری: 8765432109." in result.final_reply.text


def test_delivery_confirmation_multiple_order_ids_looks_up_each_order(monkeypatch) -> None:
    intent = IntentClassificationResult(
        primary_intent=IntentId.DELIVERY_CONFIRMATION_REQUEST,
        confidence=0.9,
        entities={"order_ids": ["INC-7338176", "INC-7337206"]},
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )
    monkeypatch.setattr("app.pipeline.run_pipeline.classify_intent", lambda *_a, **_k: intent)

    calls: list[ToolRequest] = []

    def fake_lookup(request: ToolRequest) -> ToolResult:
        from app.tools.order_lookup import run_order_lookup

        calls.append(request)
        return run_order_lookup(request, fetch_fn=lambda order_id, _shop_id, _timeout: (
            200,
            {
                "data": {
                    "order_status": "ارسال شده",
                    "providers": [
                        {
                            "shop_id": request.context.get("shop_id", "5456"),
                            "status": "ارسال شده",
                            "parcel": {
                                "status_name": "تحویل پست",
                                "tracking_code": f"track-{order_id}",
                            },
                        }
                    ],
                }
            },
        ))

    result = run_pipeline(
        "سلام سفارش های INC-7338176 - INC-7337206 تحویل داده شدند",
        metadata={"shop_id": "5456"},
        lookup_fn=fake_lookup,
    )

    assert len(calls) == 2
    assert result.order_lookup_result.successful_count == 2
    assert "وضعیت سفارش INC-7338176" in result.final_reply.text
    assert "وضعیت سفارش INC-7337206" in result.final_reply.text
