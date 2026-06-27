"""Manual debug entrypoint for Mahex tracking."""

from __future__ import annotations

import argparse
import json
import sys

from app.models.tool_contracts import ToolRequest
from app.tools.mahex_tracking import MAHEX_TRACKING_TOOL, run_mahex_tracking


def _safe_result(result) -> dict:
    return {
        "success": result.success,
        "error": result.error,
        "summary": result.summary,
        "data": result.data,
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Debug Mahex parcel tracking.")
    parser.add_argument("tracking_code", help="Mahex tracking code, e.g. 10118730244480")
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Include raw API payload in output",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    tracking_code = args.tracking_code.strip()
    if not tracking_code:
        print(json.dumps({"success": False, "error": "missing_tracking_code"}, indent=2))
        return 1

    request = ToolRequest(
        tool_name=MAHEX_TRACKING_TOOL,
        intent="shipping_inquiry",
        entities={"tracking_code": tracking_code},
    )

    raw_payload: dict | None = None

    def capture_fetch(code: str):
        nonlocal raw_payload
        from app.tools.mahex_tracking import _default_fetch

        status, payload, error = _default_fetch(code)
        if payload is not None:
            raw_payload = payload
        return status, payload, error

    result = run_mahex_tracking(
        request,
        fetch_fn=capture_fetch if args.raw else None,
    )
    output = _safe_result(result)
    if args.raw and raw_payload is not None:
        output["raw"] = raw_payload

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
