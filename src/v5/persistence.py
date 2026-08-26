from __future__ import annotations

from pathlib import Path
from typing import Any

from src.utils import append_jsonl, atomic_json, read_json
from src.v5.config_cache import ROOT, load_json_config

REGISTRY_CONFIG = "config/v5_persistence_registry.json"


def _cfg() -> dict[str, Any]:
    data = load_json_config(REGISTRY_CONFIG)
    if not isinstance(data.get("artifacts"), dict):
        raise RuntimeError("invalid V5 persistence registry")
    return data


def data_root() -> Path:
    return ROOT / str(_cfg()["data_root"])


def artifact_path(name: str) -> Path:
    filename = _cfg()["artifacts"].get(name)
    if not isinstance(filename, str):
        raise KeyError(f"unknown V5 artifact: {name}")
    return data_root() / filename


def gameweek_path(gw: int) -> Path:
    block = _cfg()["gameweek"]
    return data_root() / str(block["directory"]) / str(block["filename_template"]).format(gw=int(gw))


def read_artifact(name: str, default=None):
    return read_json(artifact_path(name), default)


def write_artifact(name: str, payload: Any) -> Path:
    path = artifact_path(name)
    atomic_json(path, payload)
    return path


def write_snapshot(snapshot: dict, *, gw: int | None = None) -> dict[str, str]:
    paths = {"latest": str(write_artifact("latest", snapshot).relative_to(ROOT))}
    if gw is not None:
        path = gameweek_path(gw)
        atomic_json(path, snapshot)
        paths["gameweek"] = str(path.relative_to(ROOT))
    if _cfg()["write_policy"].get("append_history", True):
        history = artifact_path("history")
        append_jsonl(history, snapshot)
        paths["history"] = str(history.relative_to(ROOT))
    return paths


def persistence_metadata() -> dict[str, Any]:
    cfg = _cfg()
    return {
        "data_root": str(data_root().relative_to(ROOT)),
        "separate_from_v3_v4_runtime_data": bool(cfg["write_policy"].get("separate_from_v3_v4_runtime_data", True)),
        "persist_raw_authenticated_payload": bool(cfg["write_policy"].get("persist_raw_authenticated_payload", False)),
    }
