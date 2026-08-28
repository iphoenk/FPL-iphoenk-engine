from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.v5 import V5_VERSION
from src.v5.execution_plane import current_runtime_fingerprint
from src.v5.release_integrity import build_exact_execution_fingerprint, replay_output_fingerprint

REPLAY_CONTRACT = "V5_POINT_IN_TIME_REPLAY_V1"
REPLAY_BOUNDARY = "POST_TRUTH_PRE_INTELLIGENCE"


def build_replay_capture(
    *,
    correlation_id: str,
    team_id: int,
    mode: str,
    bootstrap: dict[str, Any],
    fixtures: list[dict[str, Any]],
    truth: dict[str, Any],
    event_live: Any,
    source_fusion: dict[str, Any],
    states: dict[str, dict[str, Any]],
    runner_cfg: dict[str, Any],
    feature_switches: dict[str, Any],
    captured_at: str | None = None,
) -> dict[str, Any]:
    timestamp = captured_at or datetime.now(timezone.utc).isoformat()
    replay_inputs = {
        "bootstrap": bootstrap,
        "fixtures": fixtures,
        "truth": truth,
        "event_live": event_live,
        "source_fusion": source_fusion,
        "state_hydration": {
            "price_trajectory": (states.get("price_trajectory") or {}).get("data") or {},
            "historical_prior": (states.get("historical_prior") or {}).get("data") or {},
            "prediction_ledger": (states.get("prediction_ledger") or {}).get("data") or {},
            "challenger_observations": (states.get("challenger_observations") or {}).get("data") or {},
        },
        "runner_policy": {
            "engine_version": V5_VERSION,
            "runner_status": runner_cfg.get("status"),
            "mode": str(mode),
            "prediction_horizon_gws": int(runner_cfg.get("prediction_horizon_gws") or 0),
            "feature_switches": feature_switches,
        },
    }
    fingerprint = build_exact_execution_fingerprint(
        replay_inputs,
        correlation_id=correlation_id,
        captured_at=timestamp,
        runtime_release_fingerprint=current_runtime_fingerprint(),
    )
    return {
        "schema_version": 1,
        "contract": REPLAY_CONTRACT,
        "captured_at": timestamp,
        "correlation_id": str(correlation_id),
        "team_id": int(team_id),
        "mode": str(mode),
        "replay_boundary": REPLAY_BOUNDARY,
        "inputs": replay_inputs,
        "fingerprint": fingerprint,
        "expected_output_hashes": {},
        "governance": {
            "raw_authenticated_payload_persisted": False,
            "refetch_current_sources_on_replay": False,
            "derived_truth_is_replay_authority": True,
            "output_hashes_ignore_registry_declared_volatile_fields_only": True,
        },
    }


def finalize_replay_bundle(
    capture: dict[str, Any],
    *,
    price: dict[str, Any],
    prediction: dict[str, Any],
    evaluation: dict[str, Any],
    decision: dict[str, Any],
    framework: dict[str, Any],
) -> dict[str, Any]:
    return {
        **capture,
        "expected_output_hashes": {
            "price": replay_output_fingerprint(price),
            "prediction": replay_output_fingerprint(prediction),
            "evaluation": replay_output_fingerprint(evaluation),
            "decision": replay_output_fingerprint(decision),
            "framework": replay_output_fingerprint(framework),
        },
    }


def snapshot_fingerprint_summary(replay_bundle: dict[str, Any]) -> dict[str, Any]:
    fingerprint = replay_bundle.get("fingerprint") if isinstance(replay_bundle.get("fingerprint"), dict) else {}
    return {
        "contract": fingerprint.get("contract"),
        "runtime_release_fingerprint": fingerprint.get("runtime_release_fingerprint"),
        "code_revision": fingerprint.get("code_revision"),
        "replay_fingerprint": fingerprint.get("replay_fingerprint"),
        "execution_fingerprint": fingerprint.get("execution_fingerprint"),
        "promotion_fingerprint_complete": fingerprint.get("promotion_fingerprint_complete"),
    }
