from __future__ import annotations

from typing import Any

from src.v5.persistence import persistence_metadata, read_artifact, write_artifact, write_snapshot


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "metadata":
        return persistence_metadata()
    if operation == "read":
        return read_artifact(str(payload["name"]), payload.get("default"))
    if operation == "write":
        path = write_artifact(str(payload["name"]), payload.get("data"))
        return {"path": str(path)}
    if operation == "snapshot":
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("snapshot service requires snapshot object")
        return write_snapshot(snapshot, gw=int(payload["gw"]) if payload.get("gw") is not None else None)
    raise KeyError(f"unsupported snapshot operation: {operation}")
