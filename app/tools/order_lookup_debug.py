"""Manual debug entrypoint for order lookup."""

from __future__ import annotations

import json
import sys

from app.config import settings  # noqa: F401 - loads .env on import
from app.models.tool_contracts import ToolRequest
from app.tools.order_lookup import ORDER_LOOKUP_TOOL, run_order_lookup


def _safe_result(result) -> dict:
    return {
        "success": result.success,
        "error": result.error,
        "summary": result.summary,
        "data": result.data,
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: python -m app.tools.order_lookup_debug INC-xxxx", file=sys.stderr)
        return 2

    order_id = args[0].strip()
    request = ToolRequest(
        tool_name=ORDER_LOOKUP_TOOL,
        intent="order_status_inquiry",
        entities={"order_id": order_id},
    )
    result = run_order_lookup(request)
    print(json.dumps(_safe_result(result), ensure_ascii=False, indent=2))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
