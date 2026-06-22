from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult, SuggestedAction
from app.models.pipeline import OrderLookupExecutionResult
from app.models.reply import ReplyGenerationResult
from app.models.tool_contracts import ToolResult
from app.reply.enrichment import enrich_reply_with_order_lookup
from app.reply.templates import COMPLAINT_FOLLOWUP_REPLY, DEFAULT_REGISTERED_REPLY, DELIVERY_CONFIRMATION_REPLY
from app.tools.order_lookup import ORDER_LOOKUP_TOOL


def _reply(intent: IntentId = IntentId.ORDER_STATUS_INQUIRY) -> ReplyGenerationResult:
    return ReplyGenerationResult(
        text=DEFAULT_REGISTERED_REPLY,
        primary_intent=intent,
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )


def _intent(intent: IntentId = IntentId.ORDER_STATUS_INQUIRY) -> IntentClassificationResult:
    return IntentClassificationResult(
        primary_intent=intent,
        confidence=0.9,
        entities={"order_id": "INC-7342409"},
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )


def test_not_executed_returns_unchanged() -> None:
    original = _reply()
    result = enrich_reply_with_order_lookup(
        original,
        _intent(),
        OrderLookupExecutionResult(executed=False, tool_result=None),
    )

    assert result == original


def test_failed_lookup_returns_unchanged_with_warning() -> None:
    original = _reply()
    execution = OrderLookupExecutionResult(
        executed=True,
        tool_result=ToolResult(
            tool_name=ORDER_LOOKUP_TOOL,
            success=False,
            summary="",
            error="order_lookup_failed",
        ),
    )

    result = enrich_reply_with_order_lookup(original, _intent(), execution)

    assert result.text == original.text
    assert "order_lookup_failed" in result.warnings


def test_delivered_order_returns_delivered_only_text() -> None:
    execution = OrderLookupExecutionResult(
        executed=True,
        tool_result=ToolResult(
            tool_name=ORDER_LOOKUP_TOOL,
            success=True,
            data={
                "order_id": "INC-7342409",
                "found": "true",
                "order_status": "تحویل شده",
                "primary_parcel_status_name": "delivered",
                "primary_parcel_tracking_code": "1234567890",
                "has_parcel_tracking_code": "true",
            },
            summary="ok",
        ),
    )

    result = enrich_reply_with_order_lookup(_reply(), _intent(), execution)

    assert result.text == "وضعیت سفارش INC-7342409 در وضعیت تحویل شده قرار دارد."
    assert "کد رهگیری" not in result.text
    assert "مرسوله" not in result.text


def test_non_delivered_order_status_includes_status_and_tracking() -> None:
    execution = OrderLookupExecutionResult(
        executed=True,
        tool_result=ToolResult(
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
        ),
    )

    result = enrich_reply_with_order_lookup(_reply(), _intent(), execution)

    assert "وضعیت سفارش INC-7342409: ارسال شده." in result.text
    assert "وضعیت مرسوله: تحویل پست." in result.text
    assert "کد رهگیری: 9876543210." in result.text


def test_complaint_followup_stays_neutral_when_lookup_succeeded() -> None:
    execution = OrderLookupExecutionResult(
        executed=True,
        tool_result=ToolResult(
            tool_name=ORDER_LOOKUP_TOOL,
            success=True,
            data={
                "order_id": "INC-7342409",
                "found": "true",
                "order_status": "ارسال شده",
                "primary_parcel_tracking_code": "9876543210",
                "has_parcel_tracking_code": "true",
            },
            summary="ok",
        ),
    )

    result = enrich_reply_with_order_lookup(
        _reply(IntentId.COMPLAINT_ORDER_FOLLOWUP),
        _intent(IntentId.COMPLAINT_ORDER_FOLLOWUP),
        execution,
    )

    assert result.text == COMPLAINT_FOLLOWUP_REPLY
    assert "کد رهگیری" not in result.text


def test_delivery_confirmation_enriches_reply_with_order_status() -> None:
    execution = OrderLookupExecutionResult(
        executed=True,
        tool_result=ToolResult(
            tool_name=ORDER_LOOKUP_TOOL,
            success=True,
            data={
                "order_id": "INC-7338176",
                "found": "true",
                "order_status": "تحویل شده",
                "primary_parcel_status_name": "تحویل پست",
                "primary_parcel_tracking_code": "1234567890",
                "has_parcel_tracking_code": "true",
            },
            summary="ok",
        ),
    )

    result = enrich_reply_with_order_lookup(
        ReplyGenerationResult(
            text=DELIVERY_CONFIRMATION_REPLY,
            primary_intent=IntentId.DELIVERY_CONFIRMATION_REQUEST,
            suggested_action=SuggestedAction.REPLY_TO_SELLER,
        ),
        IntentClassificationResult(
            primary_intent=IntentId.DELIVERY_CONFIRMATION_REQUEST,
            confidence=0.9,
            entities={"order_id": "INC-7338176"},
            suggested_action=SuggestedAction.REPLY_TO_SELLER,
        ),
        execution,
    )

    assert "اطلاع شما درباره تحویل سفارش دریافت شد." in result.text
    assert "وضعیت سفارش INC-7338176: تحویل شده." in result.text
    assert "وضعیت مرسوله: تحویل پست." in result.text
    assert "کد رهگیری: 1234567890." in result.text


def test_delivery_confirmation_failed_lookup_keeps_generic_reply() -> None:
    original = ReplyGenerationResult(
        text=DELIVERY_CONFIRMATION_REPLY,
        primary_intent=IntentId.DELIVERY_CONFIRMATION_REQUEST,
        suggested_action=SuggestedAction.REPLY_TO_SELLER,
    )
    execution = OrderLookupExecutionResult(
        executed=True,
        tool_result=ToolResult(
            tool_name=ORDER_LOOKUP_TOOL,
            success=False,
            summary="",
            error="order_lookup_failed",
        ),
    )

    result = enrich_reply_with_order_lookup(
        original,
        IntentClassificationResult(
            primary_intent=IntentId.DELIVERY_CONFIRMATION_REQUEST,
            confidence=0.9,
            entities={"order_id": "INC-7338176"},
            suggested_action=SuggestedAction.REPLY_TO_SELLER,
        ),
        execution,
    )

    assert result.text == DELIVERY_CONFIRMATION_REPLY
    assert "order_lookup_failed" in result.warnings


def test_multi_order_delivery_confirmation_enrichment() -> None:
    execution = OrderLookupExecutionResult(
        executed=True,
        results=[
            ToolResult(
                tool_name=ORDER_LOOKUP_TOOL,
                success=True,
                data={
                    "order_id": "INC-7338176",
                    "found": "true",
                    "order_status": "تحویل شده",
                    "primary_parcel_status_name": "تحویل پست",
                    "primary_parcel_tracking_code": "1111111111",
                    "has_parcel_tracking_code": "true",
                },
                summary="ok",
            ),
            ToolResult(
                tool_name=ORDER_LOOKUP_TOOL,
                success=True,
                data={
                    "order_id": "INC-7337206",
                    "found": "true",
                    "order_status": "نهایی شده",
                    "primary_parcel_status_name": "تحویل مشتری",
                    "primary_parcel_tracking_code": "2222222222",
                    "has_parcel_tracking_code": "true",
                },
                summary="ok",
            ),
        ],
        successful_count=2,
        failed_count=0,
    )

    result = enrich_reply_with_order_lookup(
        ReplyGenerationResult(
            text=DELIVERY_CONFIRMATION_REPLY,
            primary_intent=IntentId.DELIVERY_CONFIRMATION_REQUEST,
            suggested_action=SuggestedAction.REPLY_TO_SELLER,
        ),
        IntentClassificationResult(
            primary_intent=IntentId.DELIVERY_CONFIRMATION_REQUEST,
            confidence=0.9,
            entities={"order_ids": ["INC-7338176", "INC-7337206"]},
            suggested_action=SuggestedAction.REPLY_TO_SELLER,
        ),
        execution,
    )

    assert "اطلاع شما درباره تحویل سفارش‌ها دریافت شد." in result.text
    assert "وضعیت سفارش INC-7338176: تحویل شده." in result.text
    assert "وضعیت سفارش INC-7337206: نهایی شده." in result.text
    assert "کد رهگیری: 1111111111." in result.text
    assert "کد رهگیری: 2222222222." in result.text


def test_partial_lookup_failure_includes_successful_orders_and_warning() -> None:
    execution = OrderLookupExecutionResult(
        executed=True,
        results=[
            ToolResult(
                tool_name=ORDER_LOOKUP_TOOL,
                success=True,
                data={
                    "order_id": "INC-7338176",
                    "found": "true",
                    "order_status": "تحویل شده",
                    "primary_parcel_status_name": "تحویل پست",
                    "has_parcel_tracking_code": "false",
                },
                summary="ok",
            ),
            ToolResult(
                tool_name=ORDER_LOOKUP_TOOL,
                success=False,
                summary="",
                error="order_lookup_failed",
            ),
        ],
        successful_count=1,
        failed_count=1,
    )

    result = enrich_reply_with_order_lookup(
        ReplyGenerationResult(
            text=DELIVERY_CONFIRMATION_REPLY,
            primary_intent=IntentId.DELIVERY_CONFIRMATION_REQUEST,
            suggested_action=SuggestedAction.REPLY_TO_SELLER,
        ),
        IntentClassificationResult(
            primary_intent=IntentId.DELIVERY_CONFIRMATION_REQUEST,
            confidence=0.9,
            entities={"order_ids": ["INC-7338176", "INC-7337206"]},
            suggested_action=SuggestedAction.REPLY_TO_SELLER,
        ),
        execution,
    )

    assert "وضعیت سفارش INC-7338176: تحویل شده." in result.text
    assert "order_lookup_partial_failure" in result.warnings
    assert "order_lookup_failed" not in result.warnings


def test_multi_order_status_inquiry_enrichment() -> None:
    execution = OrderLookupExecutionResult(
        executed=True,
        results=[
            ToolResult(
                tool_name=ORDER_LOOKUP_TOOL,
                success=True,
                data={
                    "order_id": "INC-7338176",
                    "found": "true",
                    "order_status": "ارسال شده",
                    "primary_parcel_status_name": "تحویل پست",
                    "has_parcel_tracking_code": "false",
                },
                summary="ok",
            ),
            ToolResult(
                tool_name=ORDER_LOOKUP_TOOL,
                success=True,
                data={
                    "order_id": "INC-7337206",
                    "found": "true",
                    "order_status": "ارسال شده",
                    "primary_parcel_status_name": "تحویل مشتری",
                    "has_parcel_tracking_code": "false",
                },
                summary="ok",
            ),
        ],
        successful_count=2,
        failed_count=0,
    )

    result = enrich_reply_with_order_lookup(_reply(), _intent(), execution)

    assert "وضعیت سفارش INC-7338176: ارسال شده." in result.text
    assert "وضعیت سفارش INC-7337206: ارسال شده." in result.text
