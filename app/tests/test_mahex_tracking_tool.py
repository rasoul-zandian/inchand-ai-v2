import json

from app.models.tool_contracts import ToolRequest
from app.tools.mahex_tracking import (
    MAHEX_TRACKING_TOOL,
    is_mahex_tracking_code,
    run_mahex_tracking,
)


def _sample_payload() -> dict:
    return {
        "consignmentId": "10118730244480",
        "currentStateName": "تحویل شد",
        "actualDeliveryDate": "1405-04-02 15:13:00",
        "currentStates": [
            {
                "actionDatetime": "1405-04-02 15:16:32",
                "statusCode": "DELIVERED",
                "statusName": "تحویل مرسوله به گیرنده",
            }
        ],
    }


def _request(tracking_code: str = "10118730244480") -> ToolRequest:
    return ToolRequest(
        tool_name=MAHEX_TRACKING_TOOL,
        intent="shipping_inquiry",
        entities={"tracking_code": tracking_code},
    )


def test_successful_mahex_response_maps_to_normalized_tool_result() -> None:
    def fake_fetch(_code: str):
        return 200, _sample_payload(), None

    result = run_mahex_tracking(_request(), fetch_fn=fake_fetch)

    assert result.success is True
    assert result.data["tracking_code"] == "10118730244480"
    assert result.data["carrier"] == "mahex"
    assert result.data["found"] == "true"
    assert result.data["current_state_name"] == "تحویل شد"
    assert result.data["status_text"] == "تحویل مرسوله به گیرنده"
    assert result.data["delivered"] == "true"
    assert result.data["http_status"] == "200"
    assert result.data["last_update"] == "1405-04-02 15:16:32"
    assert result.error is None


def test_timeout_returns_safe_failure() -> None:
    def fake_fetch(_code: str):
        return 0, None, "timeout"

    result = run_mahex_tracking(_request(), fetch_fn=fake_fetch)

    assert result.success is False
    assert result.error == "mahex_tracking_timeout"
    assert result.data["found"] == "false"
    assert result.data["carrier"] == "mahex"


def test_not_found_returns_safe_failure() -> None:
    def fake_fetch(_code: str):
        return 404, None, "http_error"

    result = run_mahex_tracking(_request(), fetch_fn=fake_fetch)

    assert result.success is False
    assert result.error == "mahex_tracking_not_found"
    assert result.data["http_status"] == "404"
    assert result.data["found"] == "false"


def test_invalid_response_without_consignment_id_is_not_found() -> None:
    def fake_fetch(_code: str):
        return 200, {}, None

    result = run_mahex_tracking(_request(), fetch_fn=fake_fetch)

    assert result.success is False
    assert result.error == "mahex_tracking_not_found"


def test_is_mahex_tracking_code_matches_14_digits() -> None:
    assert is_mahex_tracking_code("10118730244480") is True
    assert is_mahex_tracking_code("1234567890") is False


def test_missing_tracking_code_returns_validation_failure() -> None:
    result = run_mahex_tracking(
        ToolRequest(tool_name=MAHEX_TRACKING_TOOL, intent="shipping_inquiry", entities={})
    )

    assert result.success is False
    assert result.error == "missing_tracking_code"


def test_debug_cli_prints_safe_result_json(capsys) -> None:
    from app.tools.mahex_tracking_debug import main

    def fake_fetch(_code: str):
        return 200, _sample_payload(), None

    import app.tools.mahex_tracking_debug as debug_module

    original = debug_module.run_mahex_tracking

    def fake_run(request, fetch_fn=None):
        return original(request, fetch_fn=fake_fetch)

    debug_module.run_mahex_tracking = fake_run
    try:
        exit_code = main(["10118730244480"])
    finally:
        debug_module.run_mahex_tracking = original

    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["success"] is True
    assert payload["data"]["tracking_code"] == "10118730244480"
    assert "raw" not in payload

