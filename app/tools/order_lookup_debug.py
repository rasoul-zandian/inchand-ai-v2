"""Manual debug entrypoint for order lookup."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _apply_env_to_settings() -> None:
    from app.config import settings

    settings.inchand_api_base_url = os.getenv("INCHAND_API_BASE_URL", "")
    settings.inchand_api_key_name = os.getenv("INCHAND_API_KEY_NAME", "Authorization")
    settings.inchand_api_key_value = os.getenv("INCHAND_API_KEY_VALUE") or os.getenv(
        "INCHAND_INTERNAL_TOKEN", ""
    )
    settings.inchand_order_lookup_timeout_seconds = float(
        os.getenv("INCHAND_ORDER_LOOKUP_TIMEOUT_SECONDS", "10")
    )


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

    _load_env_file(Path(".env"))
    _apply_env_to_settings()

    from app.models.tool_contracts import ToolRequest
    from app.tools.order_lookup import ORDER_LOOKUP_TOOL, run_order_lookup

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
