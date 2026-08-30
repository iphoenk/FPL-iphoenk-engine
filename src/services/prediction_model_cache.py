from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import perf_counter

from src.engines.v4_preseason_evidence import EVIDENCE as PRESEASON_EVIDENCE, attach_preseason_evidence
from src.engines.v4_runner import build_predictions as canonical_build_predictions
from src.services.contracts import file_digest
from src.utils import CONFIG, DATA, ROOT, atomic_json, read_json

CACHE = DATA / "predictions_base_hot_cache_v4.json"
ALGORITHM = "v4.9.6-exact-base-prediction-cache-v4"
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
        "preseason_consumer": ROOT / "src/engines/v4_preseason_evidence.py",
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
        "preseason": PRESEASON_EVIDENCE,
    }
    return {name: _digest_if_exists(path) for name, path in paths.items()}


def semantic_fingerprint(bootstrap: dict, fixtures: list[dict], stats_gw: int | None) -> str:
    """Fingerprint every semantic input consumed by canonical build_predictions."""
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


def _restamp_prediction_contract(predictions: dict, generated_at: str) -> dict:
    """Restamp only timestamp fields defined by the prediction output contract."""
    predictions["generated_at"] = generated_at
    for player in predictions.get("players") or []:
        for fixture in player.get("fixtures") or []:
            provenance = fixture.get("provenance")
            if isinstance(provenance, dict) and isinstance(provenance.get("point_in_time"), str):
                provenance["point_in_time"] = generated_at
    return predictions


def _restamp(value, generated_at: str):
    if not isinstance(value, dict):
        return value
    return _restamp_prediction_contract(value, generated_at)


def _attach_current_evidence(predictions: dict) -> dict:
    # Preseason is a governed optional evidence layer. It is deliberately attached
    # after base-cache retrieval so missing evidence never invalidates canonical
    # model truth, while a verified evidence-file digest still participates in the
    # semantic fingerprint and therefore invalidates stale cache state when supplied.
    return attach_preseason_evidence(predictions)


def build_predictions_cached(bootstrap: dict, fixtures: list[dict], generated_at: str, stats_gw: int | None = None) -> dict:
    global _LAST_STATUS
    started = perf_counter()
    t = perf_counter()
    fingerprint = semantic_fingerprint(bootstrap, fixtures, stats_gw)
    fingerprint_ms = round((perf_counter() - t) * 1000.0, 2)

    t = perf_counter()
    cached = read_json(CACHE, {})
    cache_read_ms = round((perf_counter() - t) * 1000.0, 2)
    if cached.get("algorithm") == ALGORITHM and cached.get("fingerprint") == fingerprint and (cached.get("predictions") or {}).get("players"):
        t = perf_counter()
        predictions = _attach_current_evidence(_restamp_prediction_contract(cached["predictions"], generated_at))
        restamp_ms = round((perf_counter() - t) * 1000.0, 2)
        _LAST_STATUS = {
            "hit": True,
            "reason": "EXACT_SEMANTIC_MATCH",
            "fingerprint": fingerprint,
            "fingerprint_ms": fingerprint_ms,
            "cache_read_ms": cache_read_ms,
            "restamp_ms": restamp_ms,
            "canonical_build_ms": 0.0,
            "total_ms": round((perf_counter() - started) * 1000.0, 2),
        }
        return predictions

    t = perf_counter()
    predictions = canonical_build_predictions(bootstrap, fixtures, generated_at, stats_gw=stats_gw)
    canonical_build_ms = round((perf_counter() - t) * 1000.0, 2)
    t = perf_counter()
    atomic_json(CACHE, {
        "schema_version": 4,
        "algorithm": ALGORITHM,
        "fingerprint": fingerprint,
        "predictions": predictions,
        "guardrails": {
            "canonical_builder_on_miss": True,
            "all_semantic_prediction_inputs_hashed": True,
            "model_source_digest_invalidates_cache": True,
            "prediction_contract_timestamp_restamp_only": True,
            "boolean_point_in_time_truth_preserved": True,
            "competitive_load_and_team_news_attached_after_base_cache": True,
            "preseason_evidence_attached_after_base_cache": True,
            "preseason_evidence_never_fabricated": True,
            "preseason_direct_xpts_mutation": False,
        },
    })
    cache_write_ms = round((perf_counter() - t) * 1000.0, 2)
    predictions = _attach_current_evidence(predictions)
    _LAST_STATUS = {
        "hit": False,
        "reason": "CACHE_MISS_REBUILT_CANONICAL",
        "fingerprint": fingerprint,
        "fingerprint_ms": fingerprint_ms,
        "cache_read_ms": cache_read_ms,
        "restamp_ms": 0.0,
        "canonical_build_ms": canonical_build_ms,
        "cache_write_ms": cache_write_ms,
        "total_ms": round((perf_counter() - started) * 1000.0, 2),
    }
    return predictions


def last_status() -> dict:
    return dict(_LAST_STATUS)
