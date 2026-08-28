from __future__ import annotations

from typing import Any

from src.v5.architecture_guard import run_audit

BASE_CAPABILITIES = ["architecture_ownership_audit", "no_duplicate_gate"]


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {
            "status": "ACTIVE",
            "critical_path": False,
            "capabilities": list(BASE_CAPABILITIES),
            "operations": ["audit"],
            "promotion_blocking": True,
        }
    if operation == "audit":
        return run_audit()
    raise KeyError(f"unsupported architecture_guard operation: {operation}")
