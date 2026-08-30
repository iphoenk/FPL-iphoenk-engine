from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.utils import append_jsonl, atomic_json, parse_dt, read_json
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


def _history_retention() -> dict[str, Any]:
    policy = (_cfg().get("write_policy") or {}).get("history_retention") or {}
    if not isinstance(policy, dict):
        raise RuntimeError("invalid V5 history retention policy")
    return policy


def _history_timestamp(payload: Any) -> datetime | None:
    if not isinstance(payload, dict):
        return None
    for key in ("generated_at", "captured_at", "created_at"):
        value = parse_dt(payload.get(key))
        if value is not None:
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
    return None


def _compact_history(path: Path, *, now: datetime | None = None) -> dict[str, int]:
    """Bound non-canonical rolling history without touching canonical GW/ledger evidence.

    History is useful for short-horizon debugging and delta inspection, but it is not the
    season evidence authority. Retention is therefore bounded by age, record count and
    bytes. Canonical prediction evidence remains in prediction_ledger.json and gw/*.json.
    """
    policy = _history_retention()
    if not path.exists():
        return {"before_records": 0, "after_records": 0, "after_bytes": 0}

    raw_lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    before_records = len(raw_lines)
    records: list[tuple[str, Any]] = []
    for line in raw_lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            payload = None
        records.append((line, payload))

    max_age_days = int(policy.get("max_age_days") or 0)
    if max_age_days > 0:
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        cutoff = reference.astimezone(timezone.utc) - timedelta(days=max_age_days)
        records = [
            row
            for row in records
            if (stamp := _history_timestamp(row[1])) is None or stamp >= cutoff
        ]

    max_records = int(policy.get("max_records") or 0)
    if max_records > 0 and len(records) > max_records:
        records = records[-max_records:]

    max_bytes = int(policy.get("max_bytes") or 0)
    preserve_newest = bool(policy.get("preserve_newest_record", True))
    if max_bytes > 0:
        while len(records) > (1 if preserve_newest else 0):
            encoded = ("\n".join(row[0] for row in records) + "\n").encode("utf-8") if records else b""
            if len(encoded) <= max_bytes:
                break
            records.pop(0)

    content = "\n".join(row[0] for row in records)
    if content:
        content += "\n"
    current = path.read_text(encoding="utf-8")
    if content != current:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)

    after_bytes = path.stat().st_size if path.exists() else 0
    return {
        "before_records": before_records,
        "after_records": len(records),
        "after_bytes": int(after_bytes),
    }


def write_snapshot(snapshot: dict, *, gw: int | None = None) -> dict[str, str]:
    paths = {"latest": str(write_artifact("latest", snapshot).relative_to(ROOT))}
    if gw is not None:
        path = gameweek_path(gw)
        atomic_json(path, snapshot)
        paths["gameweek"] = str(path.relative_to(ROOT))
    if _cfg()["write_policy"].get("append_history", True):
        history = artifact_path("history")
        append_jsonl(history, snapshot)
        _compact_history(history)
        paths["history"] = str(history.relative_to(ROOT))
    return paths


def persistence_metadata() -> dict[str, Any]:
    cfg = _cfg()
    write_policy = cfg.get("write_policy") or {}
    return {
        "data_root": str(data_root().relative_to(ROOT)),
        "separate_from_v3_v4_runtime_data": bool(write_policy.get("separate_from_v3_v4_runtime_data", True)),
        "persist_raw_authenticated_payload": bool(write_policy.get("persist_raw_authenticated_payload", False)),
        "history_retention": dict(write_policy.get("history_retention") or {}),
        "evidence_storage": dict(cfg.get("evidence_storage") or {}),
    }
