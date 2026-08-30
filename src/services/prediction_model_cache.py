from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import perf_counter

from src.engines.v4_preseason_evidence import EVIDENCE as PRESEASON_EVIDENCE
from src.engines.v4_runner import build_predictions as canonical_build_predictions
from src.services.contracts import file_digest
from src.utils import CONFIG, DATA, ROOT, atomic_json, read_json

CACHE = DATA / "predictions_base_hot_cache_v4.json"
ALGORITHM = "v4.9.6-exact-base-prediction-cache-v7"
_LAST_STATUS: dict = {}

# Official FPL exposes fields that can change minute-to-minute but are not read
# anywhere by the canonical prediction builder. Hashing them forced unnecessary
# full model rebuilds on otherwise semantically identical refreshes. They remain
# available to their factual/market layers and are excluded only from the exact
# base-prediction fingerprint.
NON_MODEL_ELEMENT_FIELDS = {
    "transfers_in",
    "transfers_out",
    "transfers_in_event",
    "transfers_out_event",
    "cost_change_event",
    "cost_change_event_fall",
    "cost_change_start",
    "cost_change_start_fall",
    "ep_next",
    "ep_this",
    "in_dreamteam",
    "dreamteam_count",
}

# v4_runner/opponent_defence_ratings/fixture_map consume only these fixture
# dimensions. Runtime-only fixture metadata (pulse ids, stats arrays, etc.) is
# intentionally not allowed to invalidate the prediction cache.
MODEL_FIXTURE_FIELDS = (
    "event",
    "finished",
    "team_h",
    "team_a",
    "team_h_score",
    "team_a_score",
    "kickoff_time",
    "team_h_difficulty",
    "team_a_difficulty",
)

# The canonical runner consumes the team id plus these four strength fields.
# Team names/codes are reporting identity, not prediction mathematics.
MODEL_TEAM_FIELDS = (
    "id",
    "strength_defence_home",
    "strength_defence_away",
    "strength_overall_home",
    "strength_overall_away",
)


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
    }
    return {name: _digest_if_exists(path) for name, path in paths.items()}


def _prediction_elements(elements: list[dict]) -> list[dict]:
    """Retain all Official element fields except proven non-model market counters."""
    return [
        {key: value for key, value in player.items() if key not in NON_MODEL_ELEMENT_FIELDS}
        for player in elements
    ]


def _prediction_teams(teams: list[dict]) -> list[dict]:
    return [
        {field: team.get(field) for field in MODEL_TEAM_FIELDS}
        for team in teams
    ]


def _prediction_fixtures(fixtures: list[dict]) -> list[dict]:
    return [
        {field: fixture.get(field) for field in MODEL_FIXTURE_FIELDS}
        for fixture in fixtures
    ]


def _prediction_event_state(events: list[dict]) -> dict:
    # v4_runner uses only the number of finished events to size early-season
    # xMins priors. Scores, chip counters, most-selected ids and similar event
    # telemetry cannot affect a canonical prediction.
    return {
        "events": len(events),
        "finished_events": sum(bool(event.get("finished")) for event in events),
    }


def semantic_fingerprint(bootstrap: dict, fixtures: list[dict], stats_gw: int | None) -> str:
    """Fingerprint every semantic input consumed by canonical base prediction.

    Verified preseason role evidence is consumed before projection, so its digest
    invalidates the exact base cache. Official event/fixture/team payloads are
    projected to the exact fields read by v4_runner; volatile non-model metadata
    therefore cannot create a false miss, while every consumed field still can.
    """
    payload = {
        "algorithm": ALGORITHM,
        "bootstrap": {
            "elements": _prediction_elements(bootstrap.get("elements") or []),
            "teams": _prediction_teams(bootstrap.get("teams") or []),
            "event_state": _prediction_event_state(bootstrap.get("events") or []),
        },
        "fixtures": _prediction_fixtures(fixtures),
        "stats_gw": stats_gw,
        "stats_digests": _stats_digests(stats_gw),
        "preseason_evidence_digest": _digest_if_exists(PRESEASON_EVIDENCE),
        "source_digests": _source_digest(),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _restamp_prediction_contract(predictions: dict, generated_at: str) -> dict:
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
        predictions = _restamp_prediction_contract(cached["predictions"], generated_at)
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
        "schema_version": 7,
        "algorithm": ALGORITHM,
        "fingerprint": fingerprint,
        "predictions": predictions,
        "guardrails": {
            "canonical_builder_on_miss": True,
            "all_semantic_prediction_inputs_hashed": True,
            "non_model_market_counters_excluded_from_base_fingerprint": True,
            "official_team_fixture_event_fields_projected_to_exact_model_consumption": True,
            "volatile_non_model_official_metadata_cannot_invalidate_cache": True,
            "consumed_official_fields_still_invalidate_cache": True,
            "model_source_digest_invalidates_cache": True,
            "prediction_contract_timestamp_restamp_only": True,
            "boolean_point_in_time_truth_preserved": True,
            "competitive_load_and_team_news_attached_after_base_cache": True,
            "preseason_evidence_consumed_before_projection": True,
            "preseason_evidence_digest_invalidates_base_cache": True,
            "preseason_evidence_never_fabricated": True,
            "preseason_direct_xpts_mutation": False,
        },
    })
    cache_write_ms = round((perf_counter() - t) * 1000.0, 2)
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
