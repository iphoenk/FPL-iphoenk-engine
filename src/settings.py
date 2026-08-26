from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.utils import ROOT

ENGINE_CONFIG_PATH = ROOT / "config" / "engine.json"


def _load_engine_config(path: Path = ENGINE_CONFIG_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise RuntimeError("engine config must be a JSON object")
    return payload


def _required_int(config: dict[str, Any], key: str, *, env: str | None = None, minimum: int | None = None) -> int:
    raw = os.getenv(env) if env else None
    value = raw if raw not in {None, ""} else config.get(key)
    if value is None:
        raise RuntimeError(f"engine config missing required integer: {key}")
    parsed = int(value)
    if minimum is not None and parsed < minimum:
        raise RuntimeError(f"engine config {key} must be >= {minimum}")
    return parsed


def _required_float(config: dict[str, Any], key: str, *, env: str | None = None, minimum: float | None = None) -> float:
    raw = os.getenv(env) if env else None
    value = raw if raw not in {None, ""} else config.get(key)
    if value is None:
        raise RuntimeError(f"engine config missing required number: {key}")
    parsed = float(value)
    if minimum is not None and parsed < minimum:
        raise RuntimeError(f"engine config {key} must be >= {minimum}")
    return parsed


ENGINE_CONFIG = _load_engine_config()

TEAM_ID = _required_int(ENGINE_CONFIG, "team_id", env="FPL_TEAM_ID", minimum=1)
MINIMUM_LIVE_POLL_SECONDS = _required_int(ENGINE_CONFIG, "minimum_live_poll_seconds", minimum=1)
LIVE_POLL_SECONDS = max(
    MINIMUM_LIVE_POLL_SECONDS,
    _required_int(ENGINE_CONFIG, "live_poll_seconds", env="FPL_LIVE_POLL_SECONDS", minimum=1),
)
LIVE_STREAM_HEARTBEAT_SECONDS = _required_int(ENGINE_CONFIG, "live_stream_heartbeat_seconds", minimum=1)
PROJECTION_HORIZON_GWS = _required_int(ENGINE_CONFIG, "projection_horizon_gws", minimum=1)
STRATEGIC_HORIZON_GWS = _required_int(ENGINE_CONFIG, "strategic_horizon_gws", minimum=PROJECTION_HORIZON_GWS)
PURCHASE_RECONSTRUCTION_BASELINE_GW = _required_int(
    ENGINE_CONFIG, "purchase_reconstruction_baseline_gw", minimum=1
)
PRICE_PRESSURE_LIST_SIZE = _required_int(ENGINE_CONFIG, "price_pressure_list_size", minimum=1)
PRICE_SUMMARY_LIST_SIZE = _required_int(ENGINE_CONFIG, "price_summary_list_size", minimum=1)
API_RETRIES = _required_int(ENGINE_CONFIG, "api_retries", minimum=1)
API_BACKOFF_SECONDS = _required_float(ENGINE_CONFIG, "api_backoff_seconds", minimum=0.0)
API_TIMEOUT_SECONDS = _required_int(ENGINE_CONFIG, "api_timeout_seconds", env="FPL_TIMEOUT", minimum=1)
FAIL_CLOSED = bool(ENGINE_CONFIG.get("fail_closed"))
if not FAIL_CLOSED:
    raise RuntimeError("V3 production engine requires fail_closed=true")
