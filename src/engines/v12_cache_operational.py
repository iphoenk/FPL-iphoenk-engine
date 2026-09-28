from __future__ import annotations

"""Executable cache-dependency policy for V12 warm execution.

The frozen matrix remains the expectation authority. This module turns it into
fail-closed operational decisions without rewriting the frozen definitions.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATRIX = ROOT / "config" / "performance" / "v12_cache_dependency_matrix.json"
LAYERS = ("Stage2", "P1.7", "MC", "scenario", "stability")
VALID_STATES = {"HIT", "MISS", "PARTIAL_INVALIDATION", "NOT_APPLICABLE"}

# Explicit operational hard-invalidations requested after the frozen matrix was
# authored. These are overlays, not edits to the frozen expectation matrix.
HARD_INVALIDATION_STATES: dict[str, dict[str, str]] = {
    "MODEL_VERSION": {layer: "MISS" for layer in LAYERS},
    "SCHEMA_VERSION": {layer: "MISS" for layer in LAYERS},
    "CURRENT15_CHANGE": {
        "Stage2": "HIT",
        "P1.7": "MISS",
        "MC": "MISS",
        "scenario": "MISS",
        "stability": "MISS",
    },
    "CAPTAIN_CHANGE": {
        "Stage2": "HIT",
        "P1.7": "MISS",
        "MC": "MISS",
        "scenario": "MISS",
        "stability": "MISS",
    },
    "VICE_CAPTAIN_CHANGE": {
        "Stage2": "HIT",
        "P1.7": "MISS",
        "MC": "MISS",
        "scenario": "MISS",
        "stability": "MISS",
    },
    "OFFICIAL_RESULT": {layer: "MISS" for layer in LAYERS},
    "BONUS_FINALIZATION": {layer: "MISS" for layer in LAYERS},
}

# Deterministic mapping is documented instead of silently changing the matrix.
DETERMINISTIC_CLASS_MAPPING = {
    "SET_PIECE_FACT": "SET_PIECE_ROLE",
    "MATERIAL_PROJECTION": "XMINS",
}


class CacheOperationalError(RuntimeError):
    pass


@dataclass(frozen=True)
class CachePlan:
    change_class: str
    matrix_class: str
    scope_certain: bool
    affected_dependency_keys: tuple[str, ...]
    expected: dict[str, str]
    recompute_layers: tuple[str, ...]
    reusable_layers: tuple[str, ...]
    partial_layers: tuple[str, ...]


@dataclass(frozen=True)
class CacheValidation:
    correctness: str
    performance: str
    findings: tuple[str, ...]


def load_matrix(path: Path = DEFAULT_MATRIX) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("authority") != "FPL_V12_CACHE_DEPENDENCY_MATRIX":
        raise CacheOperationalError("unsupported cache dependency authority")
    if payload.get("frozen_before_performance_ab") is not True:
        raise CacheOperationalError("cache expectations must remain frozen")
    if tuple(payload.get("layers") or ()) != LAYERS:
        raise CacheOperationalError("cache layer order mismatch")
    if set(payload.get("states") or ()) != VALID_STATES:
        raise CacheOperationalError("cache state set mismatch")
    return payload


def expected_states(
    change_class: str,
    *,
    scope_certain: bool,
    matrix: Mapping[str, Any] | None = None,
) -> tuple[str, dict[str, str]]:
    change = str(change_class or "").strip().upper()
    if not change:
        raise CacheOperationalError("change_class is required")
    if not scope_certain:
        return change, {layer: "MISS" for layer in LAYERS}
    if change in HARD_INVALIDATION_STATES:
        return change, dict(HARD_INVALIDATION_STATES[change])
    mapped = DETERMINISTIC_CLASS_MAPPING.get(change, change)
    payload = dict(matrix or load_matrix())
    row = dict((payload.get("matrix") or {}).get(mapped) or {})
    if not row:
        raise CacheOperationalError(f"unsupported change class: {change}")
    states = {layer: str(row.get(layer) or "") for layer in LAYERS}
    if any(value not in VALID_STATES for value in states.values()):
        raise CacheOperationalError(f"invalid matrix row for {mapped}")
    return mapped, states


def plan_cache_behavior(
    change_class: str,
    *,
    affected_dependency_keys: Sequence[str] = (),
    scope_certain: bool = True,
    matrix: Mapping[str, Any] | None = None,
) -> CachePlan:
    keys = tuple(sorted({str(x).strip() for x in affected_dependency_keys if str(x).strip()}))
    mapped, expected = expected_states(
        change_class,
        scope_certain=scope_certain,
        matrix=matrix,
    )
    recompute = tuple(
        layer for layer, state in expected.items()
        if state in {"MISS", "PARTIAL_INVALIDATION"}
    )
    reusable = tuple(layer for layer, state in expected.items() if state == "HIT")
    partial = tuple(
        layer for layer, state in expected.items()
        if state == "PARTIAL_INVALIDATION"
    )
    if partial and not keys:
        # A partial decision without explicit dependency keys is ambiguous.
        # Fail closed to full MISS for those layers.
        expected = dict(expected)
        for layer in partial:
            expected[layer] = "MISS"
        recompute = tuple(
            layer for layer, state in expected.items()
            if state in {"MISS", "PARTIAL_INVALIDATION"}
        )
        reusable = tuple(layer for layer, state in expected.items() if state == "HIT")
        partial = tuple()
        scope_certain = False
    return CachePlan(
        change_class=str(change_class).strip().upper(),
        matrix_class=mapped,
        scope_certain=scope_certain,
        affected_dependency_keys=keys,
        expected=expected,
        recompute_layers=recompute,
        reusable_layers=reusable,
        partial_layers=partial,
    )


def validate_actual_behavior(
    plan: CachePlan,
    *,
    actual_states: Mapping[str, str],
    reused_dependency_keys: Mapping[str, Sequence[str]] | None = None,
) -> CacheValidation:
    actual = {layer: str(actual_states.get(layer) or "").upper() for layer in LAYERS}
    missing = [layer for layer, state in actual.items() if state not in VALID_STATES]
    if missing:
        raise CacheOperationalError(f"missing/invalid actual cache states: {missing}")
    reused = {
        str(layer): {str(key) for key in keys}
        for layer, keys in (reused_dependency_keys or {}).items()
    }
    findings: list[str] = []
    correctness_fail = False
    over_invalidated = False

    for layer in LAYERS:
        expected = plan.expected[layer]
        observed = actual[layer]
        if expected == "MISS" and observed in {"HIT", "PARTIAL_INVALIDATION"}:
            correctness_fail = True
            findings.append(f"{layer}: expected MISS but actual {observed}")
        elif expected == "HIT" and observed != "HIT":
            over_invalidated = True
            findings.append(f"{layer}: expected HIT but actual {observed}")
        elif expected == "PARTIAL_INVALIDATION":
            if observed == "HIT":
                correctness_fail = True
                findings.append(f"{layer}: partial invalidation collapsed to HIT")
            elif observed == "MISS":
                over_invalidated = True
                findings.append(f"{layer}: partial invalidation became full MISS")
            elif observed == "PARTIAL_INVALIDATION":
                affected = set(plan.affected_dependency_keys)
                wrongly_reused = affected.intersection(reused.get(layer, set()))
                if wrongly_reused:
                    correctness_fail = True
                    findings.append(
                        f"{layer}: affected dependency keys reused: {sorted(wrongly_reused)}"
                    )
        elif expected == "NOT_APPLICABLE" and observed != "NOT_APPLICABLE":
            correctness_fail = True
            findings.append(f"{layer}: expected NOT_APPLICABLE but actual {observed}")

    return CacheValidation(
        correctness="CORRECTNESS_FAIL" if correctness_fail else "PASS",
        performance="PERFORMANCE_OVER_INVALIDATION" if over_invalidated else "PASS",
        findings=tuple(findings),
    )
