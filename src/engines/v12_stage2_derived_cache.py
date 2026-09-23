from __future__ import annotations

"""Exact execution cache for the public V12 analytics foundation/projections.

This module owns no football methodology.  It only reuses deterministic
foundation and projection outputs when every public factual/model input that
can affect those outputs has the same fingerprint.  Private CURRENT15/auth,
finance, mini-league state and report occurrence timestamps are intentionally
outside the key.
"""

from copy import deepcopy
import hashlib
import json
import os
import pickle
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.models.historical_projection import build as build_player_projections
from src.models.v12_analytics_foundation import (
    load_v6_analytics_foundation,
    require_match_foundation,
)

ROOT = Path(__file__).resolve().parents[2]
STAGE2_CACHE_ENV = "V12_STAGE2_DERIVED_CACHE_DIR"
STAGE2_CACHE_SCHEMA = 1

PUBLIC_SOURCE_PATHS = (
    "data/v6/normalized/sources/official_fpl.json",
    "data/v6/normalized/sources/vaastav_fpl.json",
    "data/v6/normalized/sources/understat.json",
    "data/v6/normalized/sources/statmuse.json",
    "data/v6/normalized/sources/rotowire.json",
)

MODEL_DEPENDENCY_PATHS = (
    "src/models/v12_analytics_foundation.py",
    "src/models/v12_stage1_analytics.py",
    "src/models/historical_projection.py",
    "src/engines/v12_contextual_dynamics.py",
    "src/engines/v12_player_events.py",
    "src/engines/v12_player_minutes.py",
    "src/engines/v12_position_probability_components.py",
    "src/rules.py",
    "config/intelligence/player_events.json",
    "config/intelligence/player_minutes.json",
    "config/intelligence/v12_contextual_dynamics.json",
    "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt",
)

BOOTSTRAP_ELEMENT_FIELDS = (
    "id",
    "team",
    "element_type",
    "minutes",
    "starts",
    "status",
    "chance_of_playing_next_round",
    "now_cost",
    "selected_by_percent",
    "web_name",
)


class Stage2DerivedCacheError(RuntimeError):
    pass


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
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


def _file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "MISSING"


def _model_dependency_fingerprint() -> str:
    return _fingerprint(
        {
            relative: _file_sha256(ROOT / relative)
            for relative in MODEL_DEPENDENCY_PATHS
        }
    )


def _public_source_fingerprints(
    runtime_data_root: Path,
) -> dict[str, str]:
    return {
        relative: _file_sha256(runtime_data_root / relative)
        for relative in PUBLIC_SOURCE_PATHS
    }


def _bootstrap_projection_signature(
    bootstrap: Mapping[str, Any],
) -> dict[str, Any]:
    elements = []
    for raw in bootstrap.get("elements") or []:
        if not isinstance(raw, Mapping):
            continue
        elements.append(
            {
                field: raw.get(field)
                for field in BOOTSTRAP_ELEMENT_FIELDS
            }
        )
    elements.sort(key=lambda row: int(row.get("id") or 0))
    return {
        "events": [
            dict(row)
            for row in bootstrap.get("events") or []
            if isinstance(row, Mapping)
        ],
        "teams": [
            dict(row)
            for row in bootstrap.get("teams") or []
            if isinstance(row, Mapping)
        ],
        "elements": elements,
    }


def stage2_public_input_key(
    runtime_data_root: Path,
    *,
    bootstrap: Mapping[str, Any],
    strength: Mapping[str, Any],
    planning_gw: int,
) -> str:
    """Fingerprint only public facts/model code consumed by Stage-2."""
    return _fingerprint(
        {
            "schema": STAGE2_CACHE_SCHEMA,
            "model_dependencies": _model_dependency_fingerprint(),
            "planning_gw": int(planning_gw),
            "bootstrap": _bootstrap_projection_signature(bootstrap),
            "strength": strength,
            "normalized_sources": _public_source_fingerprints(
                runtime_data_root
            ),
        }
    )


def _cache_root() -> Path | None:
    value = str(os.environ.get(STAGE2_CACHE_ENV) or "").strip()
    return Path(value) if value else None


def _cache_path(kind: str, key: str) -> Path | None:
    root = _cache_root()
    if root is None:
        return None
    return root / kind / key[:2] / f"{key}.pkl"


def _load(kind: str, key: str) -> Any | None:
    path = _cache_path(kind, key)
    if path is None or not path.is_file():
        return None
    try:
        with path.open("rb") as fh:
            payload = pickle.load(fh)
        if (
            isinstance(payload, dict)
            and int(payload.get("schema") or 0)
            == STAGE2_CACHE_SCHEMA
            and payload.get("kind") == kind
            and payload.get("key") == key
            and "value" in payload
        ):
            return deepcopy(payload["value"])
    except (
        OSError,
        EOFError,
        pickle.PickleError,
        AttributeError,
        ValueError,
        TypeError,
    ):
        return None
    return None


def _save(kind: str, key: str, value: Any) -> None:
    path = _cache_path(kind, key)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("wb") as fh:
            pickle.dump(
                {
                    "schema": STAGE2_CACHE_SCHEMA,
                    "kind": kind,
                    "key": key,
                    "value": value,
                },
                fh,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def load_or_build_foundation(
    runtime_data_root: Path,
    *,
    bootstrap: Mapping[str, Any],
    strength: Mapping[str, Any],
    planning_gw: int,
    builder: Callable[..., Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    key = stage2_public_input_key(
        runtime_data_root,
        bootstrap=bootstrap,
        strength=strength,
        planning_gw=planning_gw,
    )
    cached = _load("foundation", key)
    if isinstance(cached, Mapping):
        value = require_match_foundation(cached)
        return dict(value), {
            "cache_hit": True,
            "cache_key": key,
            "cache_kind": "foundation",
        }

    raw = (
        builder(
            runtime_data_root,
            bootstrap=bootstrap,
            planning_gw=int(planning_gw),
            strength=strength,
        )
        if builder is not None
        else load_v6_analytics_foundation(
            runtime_data_root,
            bootstrap=bootstrap,
            planning_gw=int(planning_gw),
            strength=strength,
        )
    )
    value = require_match_foundation(raw)
    _save("foundation", key, value)
    return dict(value), {
        "cache_hit": False,
        "cache_key": key,
        "cache_kind": "foundation",
    }


def load_or_build_projections(
    *,
    bootstrap: Mapping[str, Any],
    strength: Mapping[str, Any],
    planning_gw: int,
    foundation: Mapping[str, Any],
    public_input_key: str,
    builder: Callable[..., Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    key = _fingerprint(
        {
            "schema": STAGE2_CACHE_SCHEMA,
            "kind": "projections",
            "public_input_key": str(public_input_key),
            "foundation_fingerprint": _fingerprint(foundation),
        }
    )
    cached = _load("projections", key)
    if isinstance(cached, Mapping):
        return dict(cached), {
            "cache_hit": True,
            "cache_key": key,
            "cache_kind": "projections",
        }

    fn = builder or build_player_projections
    value = fn(
        dict(bootstrap),
        dict(strength),
        int(planning_gw),
        dict(foundation.get("historical_prior") or {}),
        player_features_payload=dict(
            foundation.get("player_features_payload") or {}
        ),
        player_match_rows=list(
            foundation.get("player_match_rows") or []
        ),
        opponent_history_rows=list(
            foundation.get("opponent_history_rows") or []
        ),
        opponent_history_scope=foundation.get(
            "opponent_history_scope"
        ),
    )
    if not isinstance(value, Mapping):
        raise Stage2DerivedCacheError(
            "projection builder returned non-mapping output"
        )
    result = dict(value)
    _save("projections", key, result)
    return result, {
        "cache_hit": False,
        "cache_key": key,
        "cache_kind": "projections",
    }
