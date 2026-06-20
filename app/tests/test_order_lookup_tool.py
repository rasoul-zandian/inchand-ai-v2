from app.models.tool_contracts import ToolRequest, ToolResult
from app.tools.order_lookup import ORDER_LOOKUP_TOOL, run_order_lookup


def _request(**entities: str) -> ToolRequest:
    return ToolRequest(
        tool_name=ORDER_LOOKUP_TOOL,
        intent="order_status_inquiry",
        entities=entities,
    )


def test_missing_order_id_returns_failure() -> None:
    result = run_order_lookup(_request())

    assert result.success is False
    assert result.error == "missing_order_id"
    assert result.data == {}


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
    assert "INC-7342409" in result.summary


def test_http_error_maps_to_safe_failure() -> None:
    def fake_fetch(_order_id: str, _shop_id: str | None, _timeout: float):
        return 500, {"detail": "internal server error"}

    result = run_order_lookup(_request(order_id="INC-500"), fetch_fn=fake_fetch)

    assert result.success is False
    assert result.error == "order_lookup_failed"
    assert "internal server error" not in str(result.data)
    assert result.summary == ""
