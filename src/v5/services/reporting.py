from __future__ import annotations

from typing import Any

from src.v5.reporting import build_report


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {"status": "ACTIVE", "model": "v5_decision_first_report_v1", "operations": ["build"]}
    if operation == "build":
        return build_report(payload)
    raise KeyError(f"unsupported reporting operation: {operation}")
