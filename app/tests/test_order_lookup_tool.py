from app.config import settings
from app.models.tool_contracts import ToolRequest, ToolResult
from app.tools.order_lookup import ORDER_LOOKUP_TOOL, run_order_lookup


def _request(
    *,
    context: dict[str, str] | None = None,
    **entities: str,
) -> ToolRequest:
    return ToolRequest(
        tool_name=ORDER_LOOKUP_TOOL,
        intent="order_status_inquiry",
        entities=entities,
        context=context or {},
    )


_MULTI_PROVIDER_PAYLOAD = {
    "order_status": "ارسال شده",
    "payment_status": "موفق",
    "providers": [
        {
            "shop_id": "5456",
            "status": "ارسال شده",
            "parcel": {
                "status_name": "تحویل پست",
                "tracking_code": "912660509200072100004111",
            },
        },
        {
            "shop_id": "7611",
            "status": "ارسال شده",
            "parcel": {
                "status_name": "تحویل پست",
                "tracking_code": "032930509200123380004107",
            },
        },
    ],
}


def test_missing_order_id_returns_failure() -> None:
    result = run_order_lookup(_request())

    assert result.success is False
    assert result.error == "missing_order_id"
    assert result.data == {}


def test_missing_config_reports_missing_config(monkeypatch) -> None:
    monkeypatch.setattr(settings, "inchand_api_base_url", "")
    monkeypatch.setattr(settings, "inchand_api_key_value", "")

    result = run_order_lookup(_request(order_id="INC-7342409"))

    assert result.success is False
    assert result.error == "missing_config"
    assert result.data["normalized_order_id"] == "INC-7342409"


def test_successful_mocked_response_maps_to_tool_result() -> None:
    def fake_fetch(order_id: str, shop_id: str | None, timeout: float):
        assert order_id == "INC-7342409"
        assert shop_id is None
        assert timeout > 0
        return 200, {
            "order_status": "processing",
            "payment_status": "paid",
            "is_delivered_in_inchand": False,
            "providers": [
                {
                    "id": "p1",
                    "status": "shipped",
                    "parcel": {
                        "status_name": "in_transit",
                        "tracking_code": "1234567890",
                    },
                }
            ],
        }

    result = run_order_lookup(_request(order_id="INC-7342409"), fetch_fn=fake_fetch)

    assert result.success is True
    assert result.error is None
    assert result.data["order_id"] == "INC-7342409"
    assert result.data["found"] == "true"
    assert result.data["order_status"] == "processing"
    assert result.data["payment_status"] == "paid"
    assert result.data["provider_count"] == "1"
    assert result.data["primary_provider_status"] == "shipped"
    assert result.data["primary_parcel_tracking_code"] == "1234567890"
    assert result.data["has_parcel_tracking_code"] == "true"
    assert result.data["is_shop_scoped"] == "false"
    assert "INC-7342409" in result.summary


def test_wrapped_api_response_maps_to_tool_result() -> None:
    def fake_fetch(_order_id: str, _shop_id: str | None, _timeout: float):
        return 200, {
            "data": {
                "order_status": "ارسال شده",
                "payment_status": "موفق",
                "providers": [
                    {
                        "status": "shipped",
                        "parcel": {
                            "tracking_code": "155790507900191440000114",
                            "status_detail": {"name": "تحویل مشتری"},
                        },
                    }
                ],
            }
        }

    result = run_order_lookup(_request(order_id="INC-7340086"), fetch_fn=fake_fetch)

    assert result.success is True
    assert result.data["order_status"] == "ارسال شده"
    assert result.data["primary_parcel_status_name"] == "تحویل مشتری"
    assert result.data["primary_parcel_tracking_code"] == "155790507900191440000114"


def test_auth_error_reports_safely() -> None:
    def fake_fetch(_order_id: str, _shop_id: str | None, _timeout: float):
        return 401, {"message": "unauthorized"}

    result = run_order_lookup(_request(order_id="INC-401"), fetch_fn=fake_fetch)

    assert result.success is False
    assert result.error == "auth_error"
    assert result.data["http_status"] == "401"
    assert result.data["normalized_order_id"] == "INC-401"
    assert "unauthorized" not in str(result.data)


def test_unexpected_response_shape_reports_parse_error() -> None:
    def fake_fetch(_order_id: str, _shop_id: str | None, _timeout: float):
        raise ValueError("invalid_response")

    result = run_order_lookup(_request(order_id="INC-500"), fetch_fn=fake_fetch)

    assert result.success is False
    assert result.error == "parse_error"
    assert result.data["parse_error"] == "invalid_response"
    assert result.data["normalized_order_id"] == "INC-500"


def test_http_error_maps_to_safe_failure() -> None:
    def fake_fetch(_order_id: str, _shop_id: str | None, _timeout: float):
        return 500, {"detail": "internal server error"}

    result = run_order_lookup(_request(order_id="INC-500"), fetch_fn=fake_fetch)

    assert result.success is False
    assert result.error == "order_lookup_failed"
    assert result.data["http_status"] == "500"
    assert "internal server error" not in str(result.data)
    assert result.summary == ""


def test_not_found_returns_success_with_found_false() -> None:
    def fake_fetch(_order_id: str, _shop_id: str | None, _timeout: float):
        return 404, {"message": "not found"}

    result = run_order_lookup(_request(order_id="INC-404"), fetch_fn=fake_fetch)

    assert result.success is True
    assert result.data["found"] == "false"
    assert result.data["http_status"] == "404"


def test_multi_provider_with_shop_id_selects_matching_provider() -> None:
    def fake_fetch(_order_id: str, shop_id: str | None, _timeout: float):
        assert shop_id == "5456"
        return 200, _MULTI_PROVIDER_PAYLOAD

    result = run_order_lookup(
        _request(order_id="INC-7331200", context={"shop_id": "5456"}),
        fetch_fn=fake_fetch,
    )

    assert result.success is True
    assert result.data["is_shop_scoped"] == "true"
    assert result.data["shop_provider_match"] == "true"
    assert result.data["primary_provider_shop_id"] == "5456"
    assert result.data["primary_parcel_tracking_code"] == "912660509200072100004111"


def test_multi_provider_with_other_shop_id_selects_that_provider() -> None:
    def fake_fetch(_order_id: str, shop_id: str | None, _timeout: float):
        assert shop_id == "7611"
        return 200, _MULTI_PROVIDER_PAYLOAD

    result = run_order_lookup(
        _request(order_id="INC-7331200", context={"shop_id": "7611"}),
        fetch_fn=fake_fetch,
    )

    assert result.success is True
    assert result.data["is_shop_scoped"] == "true"
    assert result.data["primary_provider_shop_id"] == "7611"
    assert result.data["primary_parcel_tracking_code"] == "032930509200123380004107"


def test_multi_provider_without_shop_id_uses_first_provider() -> None:
    def fake_fetch(_order_id: str, shop_id: str | None, _timeout: float):
        assert shop_id is None
        return 200, _MULTI_PROVIDER_PAYLOAD

    result = run_order_lookup(_request(order_id="INC-7331200"), fetch_fn=fake_fetch)

    assert result.success is True
    assert result.data["is_shop_scoped"] == "false"
    assert result.data["primary_provider_shop_id"] == "5456"
    assert result.data["primary_parcel_tracking_code"] == "912660509200072100004111"
    assert "shop_provider_match" not in result.data


def test_shop_id_without_matching_provider_marks_not_found() -> None:
    def fake_fetch(_order_id: str, _shop_id: str | None, _timeout: float):
        return 200, _MULTI_PROVIDER_PAYLOAD

    result = run_order_lookup(
        _request(order_id="INC-7331200", context={"shop_id": "9999"}),
        fetch_fn=fake_fetch,
    )

    assert result.success is True
    assert result.data["order_status"] == "ارسال شده"
    assert result.data["is_shop_scoped"] == "false"
    assert result.data["shop_provider_match"] == "false"
    assert result.data["provider_not_found_for_shop"] == "true"
    assert result.data["primary_provider_shop_id"] == ""
    assert result.data["primary_parcel_tracking_code"] == ""
