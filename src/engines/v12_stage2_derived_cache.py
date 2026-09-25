from __future__ import annotations

"""Execution-only cache for deterministic P1.1/P1.3 full-universe projections.

V6 remains factual authority and the existing historical_projection builder
remains the only Stage-2 mathematical owner. This module only fingerprints the
exact deterministic inputs/model dependencies, restores a previously computed
projection payload on an exact hit, or calls the supplied canonical builder on
a miss. Private/current-team evidence is intentionally outside the key.
"""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import pickle
import time

from typing import Any, Callable, Mapping, Sequence

from src.engines.v12_cache_runtime_identity import runtime_cache_identity

ROOT = Path(__file__).resolve().parents[2]
STAGE2_DERIVED_CACHE_ENV = "V12_STAGE2_DERIVED_CACHE_DIR"
STAGE2_DERIVED_CACHE_SCHEMA = 3

_MODEL_DEPENDENCIES = (
    "src/models/v12_analytics_foundation.py",
    "src/models/historical_projection.py",
    "src/engines/v12_contextual_dynamics.py",
    "src/engines/v12_player_events.py",
    "src/engines/v12_player_minutes.py",
    "src/engines/v12_position_probability_components.py",
    "src/engines/p0_decision_quality.py",
    "src/models/v12_stage1_analytics.py",
    "src/rules.py",
    "config/intelligence/player_events.json",
    "config/intelligence/player_minutes.json",
    "config/intelligence/historical_priors.json",
    "config/intelligence/v12_contextual_dynamics.json",
)


class Stage2DerivedCacheError(RuntimeError):
    pass


def _runtime_cache_identity() -> dict[str, Any]:
    return runtime_cache_identity()


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(
        f"Object of type {value.__class__.__name__} is not JSON serializable"
    )


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _dependency_fingerprints() -> dict[str, str]:
    out: dict[str, str] = {}
    for relative in _MODEL_DEPENDENCIES:
        path = ROOT / relative
        if not path.is_file():
            raise Stage2DerivedCacheError(
                f"required Stage-2 model dependency missing: {relative}"
            )
        out[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def stage2_derived_input_fingerprint(
    *,
    bootstrap: Mapping[str, Any],
    strength: Mapping[str, Any],
    planning_gw: int,
    historical_prior: Mapping[str, Any],
    player_features_payload: Mapping[str, Any],
    player_match_rows: Sequence[Mapping[str, Any]],
    opponent_history_rows: Sequence[Mapping[str, Any]],
    opponent_history_scope: Any,
) -> str:
    """Fingerprint only deterministic public/model inputs used by P1.1/P1.3."""
    return _fingerprint(
        {
            "schema": STAGE2_DERIVED_CACHE_SCHEMA,
            "runtime": _runtime_cache_identity(),
            "planning_gw": int(planning_gw),
            "bootstrap": bootstrap,
            "strength": strength,
            "historical_prior": historical_prior,
            "player_features_payload": player_features_payload,
            "player_match_rows": list(player_match_rows),
            "opponent_history_rows": list(opponent_history_rows),
            "opponent_history_scope": opponent_history_scope,
            "model_dependencies": _dependency_fingerprints(),
        }
    )


def load_or_build_stage2_projections(
    *,
    bootstrap: Mapping[str, Any],
    strength: Mapping[str, Any],
    planning_gw: int,
    historical_prior: Mapping[str, Any],
    player_features_payload: Mapping[str, Any],
    player_match_rows: Sequence[Mapping[str, Any]],
    opponent_history_rows: Sequence[Mapping[str, Any]],
    opponent_history_scope: Any,
    builder: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return canonical projections plus non-authoritative cache proof."""
    started = time.perf_counter()
    key = stage2_derived_input_fingerprint(
        bootstrap=bootstrap,
        strength=strength,
        planning_gw=planning_gw,
        historical_prior=historical_prior,
        player_features_payload=player_features_payload,
        player_match_rows=player_match_rows,
        opponent_history_rows=opponent_history_rows,
        opponent_history_scope=opponent_history_scope,
    )
    cache_root = str(os.environ.get(STAGE2_DERIVED_CACHE_ENV) or "").strip()
    proof = {
        "schema": STAGE2_DERIVED_CACHE_SCHEMA,
        "input_fingerprint": key,
        "cache_authoritative": False,
        "mathematical_owner_changed": False,
        "private_current15_in_key": False,
        "status": "MISS",
        "cache_hit": False,
        "cache_miss": True,
        "cache_write": False,
        "cache_corrupt_reject": False,
    }
    path: Path | None = None
    if cache_root:
        path = Path(cache_root) / key[:2] / f"{key}.pkl"
        if path.is_file():
            try:
                with path.open("rb") as fh:
                    payload = pickle.load(fh)
                if (
                    isinstance(payload, dict)
                    and int(payload.get("schema") or 0)
                    == STAGE2_DERIVED_CACHE_SCHEMA
                    and payload.get("key") == key
                    and isinstance(payload.get("projections"), dict)
                ):
                    projections = dict(payload["projections"])
                    proof.update(
                        {
                            "status": "HIT",
                            "cache_hit": True,
                            "cache_miss": False,
                            "load_or_build_seconds": round(
                                time.perf_counter() - started, 6
                            ),
                        }
                    )
                    return projections, proof
                proof["cache_corrupt_reject"] = True
            except (
                OSError,
                EOFError,
                pickle.PickleError,
                AttributeError,
                ValueError,
                TypeError,
            ):
                proof["cache_corrupt_reject"] = True

    projections = builder()
    if not isinstance(projections, dict) or not isinstance(
        projections.get("players"), list
    ):
        raise Stage2DerivedCacheError(
            "canonical Stage-2 builder returned an invalid projection payload"
        )
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with tmp.open("wb") as fh:
                pickle.dump(
                    {
                        "schema": STAGE2_DERIVED_CACHE_SCHEMA,
                        "key": key,
                        "projections": projections,
                    },
                    fh,
                    protocol=pickle.HIGHEST_PROTOCOL,
                )
            os.replace(tmp, path)
            proof["cache_write"] = True
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
    proof["load_or_build_seconds"] = round(
        time.perf_counter() - started, 6
    )
    return projections, proof
