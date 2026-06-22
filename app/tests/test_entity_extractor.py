from app.entities.extractor import extract_entities
from app.intent.classifier import classify_intent
from app.intent.taxonomy import IntentId
from app.models.messages import ConversationMessage
from app.tools.selection import ORDER_LOOKUP, select_tools


def test_extracts_inc_order_id_from_seller_message() -> None:
    result = extract_entities("وضعیت سفارش INC-7340086")

    assert result.order_id == "INC-7340086"
    assert result.order_ids == ["INC-7340086"]


def test_extracts_standalone_seven_digit_order_id() -> None:
    result = extract_entities("7337206")

    assert result.order_id == "INC-7337206"
    assert result.order_ids == ["INC-7337206"]


def test_extracts_multiple_seven_digit_order_ids() -> None:
    result = extract_entities("7338176 - 7337206")

    assert result.order_ids == ["INC-7338176", "INC-7337206"]
    assert result.order_id == "INC-7338176"


def test_extracts_raw_numeric_order_id_and_normalizes() -> None:
    result = extract_entities("شماره سفارش 7340086")

    assert result.order_id == "INC-7340086"
    assert result.order_ids == ["INC-7340086"]


def test_does_not_extract_seven_digits_from_longer_number() -> None:
    result = extract_entities("6219861091629898")

    assert result.order_id is None
    assert result.order_ids == []
    assert result.card_number == "6219861091629898"


def test_extracts_order_id_from_context_when_seller_message_lacks_it() -> None:
    context = [
        ConversationMessage(
            role="assistant",
            content="فروشنده گرامی در مورد سفارش INC-7342409 شکایتی ثبت شده است.",
        ),
    ]

    result = extract_entities("تماس گرفته شد", conversation_context=context)

    assert result.order_id == "INC-7342409"


def test_extracts_tracking_code_but_not_as_card() -> None:
    result = extract_entities("047900508700016030007111 پیگیری پست")

    assert result.tracking_code == "047900508700016030007111"
    assert result.card_number is None


def test_extracts_card_number_but_not_as_order_id() -> None:
    result = extract_entities("6219861091629898")

    assert result.card_number == "6219861091629898"
    assert result.order_id is None
    assert result.tracking_code is None


def test_extracts_mobile_number_but_not_as_order_id() -> None:
    result = extract_entities("09123456789")

    assert result.mobile_number == "09123456789"
    assert result.order_id is None


def test_extracts_iban_with_ir_prefix() -> None:
    result = extract_entities("IR510170000000216612060003")

    assert result.iban == "IR510170000000216612060003"
    assert result.tracking_code is None


def test_extracts_iban_from_labeled_sheba() -> None:
    result = extract_entities("شماره شبا: 510170000000216612060003")

    assert result.iban == "IR510170000000216612060003"
    assert result.tracking_code is None


def test_twenty_four_digit_without_sheba_is_tracking_code() -> None:
    result = extract_entities("047900508700016030007111")

    assert result.tracking_code == "047900508700016030007111"
    assert result.iban is None


def test_order_ids_to_dict_is_list() -> None:
    result = extract_entities("7338176 - 7337206")

    entities = result.to_dict()

    assert entities["order_ids"] == ["INC-7338176", "INC-7337206"]
    assert entities["order_id"] == "INC-7338176"


def test_extracts_product_id() -> None:
    result = extract_entities("لطفا محصول 12345 را بررسی کنید")

    assert result.product_id == "12345"
    assert result.product_ids == ["12345"]


def test_tool_selection_selects_order_lookup_for_order_status_with_inc_id() -> None:
    intent_result = classify_intent("وضعیت سفارش INC-7342409")

    assert intent_result.primary_intent == IntentId.ORDER_STATUS_INQUIRY
    assert intent_result.entities["order_id"] == "INC-7342409"

    tool_result = select_tools(intent_result)

    assert tool_result.selected_tools == [ORDER_LOOKUP]
    assert not tool_result.requires_human_followup
