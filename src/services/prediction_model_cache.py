from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from src.engines.v4_runner import build_predictions as canonical_build_predictions
from src.services.contracts import file_digest
from src.utils import CONFIG, DATA, ROOT, atomic_json, read_json

CACHE = DATA / "predictions_base_hot_cache_v4.json"
ALGORITHM = "v4.9.6-exact-base-prediction-cache-v2"
_LAST_STATUS: dict = {}


def _digest_if_exists(path: Path) -> str | None:
    return file_digest(path) if path.exists() else None


def _source_digest() -> dict:
    paths = {
        "runner": ROOT / "src/engines/v4_runner.py",
        "model": ROOT / "src/models/v4_prediction.py",
        "inputs": ROOT / "src/models/v4_prediction_inputs.py",
        "identity": ROOT / "src/models/player_identity.py",
        "quality": CONFIG / "prediction_quality_registry.json",
    }
    return {name: _digest_if_exists(path) for name, path in paths.items()}


def _stats_digests(stats_gw: int | None) -> dict:
    stats = DATA / "stats"
    suffix = f"gw{int(stats_gw)}" if stats_gw else None
    paths = {
        "last_season": stats / "vaastav_previous_season.json",
        "core": stats / f"core_insights_{suffix}.json" if suffix else stats / "__missing_core__",
        "shots": stats / f"shots_{suffix}.json" if suffix else stats / "__missing_shots__",
        "matches": stats / f"playermatchstats_{suffix}.json" if suffix else stats / "__missing_matches__",
    }
    return {name: _digest_if_exists(path) for name, path in paths.items()}


def semantic_fingerprint(bootstrap: dict, fixtures: list[dict], stats_gw: int | None) -> str:
    """Fingerprint every semantic input consumed by canonical build_predictions.

    Runtime timestamps are deliberately absent. Any model source, quality registry,
    current bootstrap/fixture fact or prediction-enrichment file change invalidates
    reuse and falls back to the canonical full calculation.
    """
    payload = {
        "algorithm": ALGORITHM,
        "bootstrap": {
            "elements": bootstrap.get("elements") or [],
            "teams": bootstrap.get("teams") or [],
            "events": bootstrap.get("events") or [],
        },
        "fixtures": fixtures,
        "stats_gw": stats_gw,
        "stats_digests": _stats_digests(stats_gw),
        "source_digests": _source_digest(),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _restamp(value, generated_at: str):
    """Refresh timestamp provenance while preserving boolean point-in-time truth."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == "generated_at":
                out[key] = generated_at
            elif key == "point_in_time" and isinstance(item, str):
                out[key] = generated_at
            else:
                out[key] = _restamp(item, generated_at)
        return out
    if isinstance(value, list):
        return [_restamp(item, generated_at) for item in value]
    return value


def build_predictions_cached(bootstrap: dict, fixtures: list[dict], generated_at: str, stats_gw: int | None = None) -> dict:
    global _LAST_STATUS
    fingerprint = semantic_fingerprint(bootstrap, fixtures, stats_gw)
    cached = read_json(CACHE, {})
    if cached.get("algorithm") == ALGORITHM and cached.get("fingerprint") == fingerprint and (cached.get("predictions") or {}).get("players"):
        predictions = _restamp(copy.deepcopy(cached["predictions"]), generated_at)
        _LAST_STATUS = {"hit": True, "reason": "EXACT_SEMANTIC_MATCH", "fingerprint": fingerprint}
        return predictions

    predictions = canonical_build_predictions(bootstrap, fixtures, generated_at, stats_gw=stats_gw)
    atomic_json(CACHE, {
        "schema_version": 2,
        "algorithm": ALGORITHM,
        "fingerprint": fingerprint,
        "predictions": predictions,
        "guardrails": {
            "canonical_builder_on_miss": True,
            "all_semantic_prediction_inputs_hashed": True,
            "model_source_digest_invalidates_cache": True,
            "generated_timestamp_restamped": True,
            "boolean_point_in_time_truth_preserved": True,
            "string_point_in_time_provenance_restamped": True,
            "competitive_load_and_team_news_attached_after_base_cache": True,
        },
    })
    _LAST_STATUS = {"hit": False, "reason": "CACHE_MISS_REBUILT_CANONICAL", "fingerprint": fingerprint}
    return predictions


def last_status() -> dict:
    return dict(_LAST_STATUS)
