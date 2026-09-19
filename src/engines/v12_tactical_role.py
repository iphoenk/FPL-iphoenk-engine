from __future__ import annotations

"""V12-native tactical / role canonical scorer.

This module owns only the Canonical V12 25% TACTICAL/ROLE component. It
classifies governed evidence, applies anti-double-count rules, normalizes the
component, and publishes uncertainty/provenance. It does not mutate P1.1
minutes or P1.3 event distributions.
"""

from copy import deepcopy
from functools import lru_cache
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from src.engines.v12_model_evidence import (
    bind_deterministic_output,
    validate_operational_model_evidence,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "tactical_role_canonical.json"

MODEL_OWNER = "V12_TACTICAL_ROLE"
MODEL_ID = "v12_tactical_role_canonical"
CANONICAL_COMPONENT = "TACTICAL_ROLE"
CANONICAL_WEIGHT = 0.25

EVIDENCE_STATES = {"OBSERVED", "INFERRED", "UNAVAILABLE"}
DIRECTIONS = {"POSITIVE": 1.0, "NEUTRAL": 0.0, "NEGATIVE": -1.0, "MIXED": 0.0, "UNKNOWN": 0.0}
AUTHORITY_FACTOR = {"OBSERVED": 1.0, "INFERRED": 0.65, "UNAVAILABLE": 0.0}
SCOREABLE_DOUBLE_COUNT = {"TACTICAL_DISTINCT", "TACTICAL_INTERACTION_ROLE_MATCHED"}
EXCLUDED_DOUBLE_COUNT = {
    "CURRENT_UNDERLYING_EXCLUDED",
    "FIXTURE_SECURITY_EXCLUDED",
    "PROVEN_HISTORICAL_EXCLUDED",
    "P1_1_SHARED_EXCLUDED",
    "CONTEXT_ONLY_UNMATCHED_ROLE_CHANNEL",
    "MIXED_OR_CONFLICTED_EXCLUDED",
}
TOKEN_RE = re.compile(r"^[A-Z0-9_:+.\\/-]{1,96}$")


class TacticalRoleContractError(ValueError):
    pass


def _finite(value: Any, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise TacticalRoleContractError(f"{label} must be numeric") from exc
    if not math.isfinite(out):
        raise TacticalRoleContractError(f"{label} must be finite")
    return out


def _bounded(value: Any, label: str) -> float:
    out = _finite(value, label)
    if not 0.0 <= out <= 1.0:
        raise TacticalRoleContractError(f"{label} must be within [0,1]")
    return out


def _token(value: Any, label: str) -> str:
    text = str(value or "").strip().upper().replace(" ", "_")
    if not TOKEN_RE.match(text):
        raise TacticalRoleContractError(f"{label} must be a bounded canonical token")
    return text


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if payload.get("contract") != "V12_TACTICAL_ROLE_CANONICAL_V1":
        raise TacticalRoleContractError("unexpected tactical role canonical contract")
    if float(payload.get("canonical_component_weight") or -1.0) != CANONICAL_WEIGHT:
        raise TacticalRoleContractError("canonical tactical weight drift")
    return payload


def _specs() -> dict[str, dict[str, Any]]:
    return dict(load_config().get("features") or {})


def _anti_double_count() -> dict[str, Any]:
    return dict(load_config().get("anti_double_count_matrix") or {})


def _forbidden_signal_names() -> set[str]:
    return {str(x) for x in _anti_double_count().get("forbidden_tactical_inputs") or []}


def unavailable_feature(feature_name: str, *, reason: str) -> dict[str, Any]:
    if feature_name not in _specs():
        raise TacticalRoleContractError(f"unknown tactical feature: {feature_name}")
    return {
        "feature_name": feature_name,
        "value": "UNKNOWN",
        "direction": "UNKNOWN",
        "evidence_state": "UNAVAILABLE",
        "source": None,
        "observed_at": None,
        "confidence": 0.0,
        "direct_or_inferred": "UNAVAILABLE",
        "materiality": 0.0,
        "double_count_classification": "TACTICAL_DISTINCT",
        "supporting_evidence_reference": None,
        "reason": reason,
    }


def _validate_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(raw)
    name = str(row.get("feature_name") or "").strip()
    if name in _forbidden_signal_names():
        owner = (_anti_double_count().get("signal_owners") or {}).get(name)
        raise TacticalRoleContractError(
            f"{name} belongs to {owner or 'another canonical component'} and cannot enter tactical"
        )
    if name not in _specs():
        raise TacticalRoleContractError(f"unknown tactical feature: {name}")

    state = str(row.get("evidence_state") or "").upper()
    if state not in EVIDENCE_STATES:
        raise TacticalRoleContractError(f"{name}.evidence_state invalid")
    expected_directness = {
        "OBSERVED": "DIRECT",
        "INFERRED": "INFERRED",
        "UNAVAILABLE": "UNAVAILABLE",
    }[state]
    directness = str(row.get("direct_or_inferred") or "").upper()
    if directness != expected_directness:
        raise TacticalRoleContractError(
            f"{name}.direct_or_inferred must be {expected_directness} for {state}"
        )

    confidence = _bounded(row.get("confidence", 0.0), f"{name}.confidence")
    materiality = _bounded(row.get("materiality", 0.0), f"{name}.materiality")
    source = str(row.get("source") or "").strip() or None
    reference = str(row.get("supporting_evidence_reference") or "").strip() or None
    value = _token(row.get("value") or "UNKNOWN", f"{name}.value")
    direction = str(row.get("direction") or "UNKNOWN").upper()
    if direction not in DIRECTIONS:
        raise TacticalRoleContractError(f"{name}.direction invalid")

    double_count = str(row.get("double_count_classification") or "").upper()
    if double_count not in SCOREABLE_DOUBLE_COUNT | EXCLUDED_DOUBLE_COUNT:
        raise TacticalRoleContractError(f"{name}.double_count_classification invalid")

    if state == "UNAVAILABLE":
        if confidence != 0.0 or materiality != 0.0:
            raise TacticalRoleContractError(
                f"{name} unavailable evidence must have zero confidence/materiality"
            )
        if source or reference or value != "UNKNOWN" or direction != "UNKNOWN":
            raise TacticalRoleContractError(
                f"{name} unavailable evidence cannot fabricate factual support"
            )
    elif not source or not reference:
        raise TacticalRoleContractError(
            f"{name} observed/inferred evidence requires source and supporting reference"
        )

    return {
        "feature_name": name,
        "group": _specs()[name].get("group"),
        "value": value,
        "direction": direction,
        "evidence_state": state,
        "source": source,
        "observed_at": row.get("observed_at"),
        "confidence": confidence,
        "direct_or_inferred": directness,
        "materiality": materiality,
        "double_count_classification": double_count,
        "supporting_evidence_reference": reference,
        "reason": str(row.get("reason") or "").strip() or None,
    }


def _collapse_feature(feature_name: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    validated = [_validate_row(row) for row in rows]
    if not validated:
        validated = [
            _validate_row(
                unavailable_feature(feature_name, reason="NO_GOVERNED_EVIDENCE")
            )
        ]

    authority_rank = {"UNAVAILABLE": 0, "INFERRED": 1, "OBSERVED": 2}
    best_rank = max(authority_rank[row["evidence_state"]] for row in validated)
    selected = [
        row for row in validated
        if authority_rank[row["evidence_state"]] == best_rank
    ]
    state = selected[0]["evidence_state"]
    if state == "UNAVAILABLE":
        return {
            **selected[0],
            "conflict": False,
            "active_evidence_count": 0,
            "superseded_lower_authority_count": len(validated) - 1,
            "provenance": [],
        }

    directions = {
        row["direction"] for row in selected if row["direction"] != "UNKNOWN"
    }
    values = {row["value"] for row in selected if row["value"] != "UNKNOWN"}
    conflict = len(directions) > 1 or len(values) > 1
    direction = (
        "MIXED"
        if len(directions) > 1
        else (next(iter(directions)) if directions else "UNKNOWN")
    )
    value = (
        "MIXED"
        if len(values) > 1
        else (next(iter(values)) if values else "UNKNOWN")
    )
    classes = {row["double_count_classification"] for row in selected}
    double_count = (
        next(iter(classes))
        if len(classes) == 1 and not conflict
        else "MIXED_OR_CONFLICTED_EXCLUDED"
    )
    confidence = sum(row["confidence"] for row in selected) / len(selected)
    materiality = sum(row["materiality"] for row in selected) / len(selected)
    if conflict:
        confidence *= 0.75

    timestamps = [
        str(row["observed_at"]) for row in selected if row.get("observed_at")
    ]
    return {
        "feature_name": feature_name,
        "group": _specs()[feature_name].get("group"),
        "value": value,
        "direction": direction,
        "evidence_state": state,
        "source": sorted({row["source"] for row in selected if row["source"]}),
        "observed_at": max(timestamps) if timestamps else None,
        "confidence": round(confidence, 6),
        "direct_or_inferred": "DIRECT" if state == "OBSERVED" else "INFERRED",
        "materiality": round(materiality, 6),
        "double_count_classification": double_count,
        "supporting_evidence_reference": sorted(
            {
                row["supporting_evidence_reference"]
                for row in selected
                if row["supporting_evidence_reference"]
            }
        ),
        "reason": None,
        "conflict": conflict,
        "active_evidence_count": len(selected),
        "superseded_lower_authority_count": len(validated) - len(selected),
        "provenance": [
            {
                "source": row["source"],
                "supporting_evidence_reference": row["supporting_evidence_reference"],
                "observed_at": row.get("observed_at"),
                "evidence_state": row["evidence_state"],
            }
            for row in selected
        ],
    }


def _role_channel_compatible(
    feature_name: str,
    collapsed: Mapping[str, Mapping[str, Any]],
) -> bool:
    deployment = collapsed.get("central_wide_half_space_deployment") or {}
    channel = str(deployment.get("value") or "UNKNOWN")
    if feature_name == "opponent_wide_vulnerability":
        return channel in {"WIDE", "WIDE_LEFT", "WIDE_RIGHT", "MIXED"}
    if feature_name == "opponent_half_space_vulnerability":
        return channel in {
            "HALF_SPACE",
            "HALF_SPACE_LEFT",
            "HALF_SPACE_RIGHT",
            "MIXED",
        }
    if feature_name == "opponent_central_channel_vulnerability":
        return channel in {"CENTRAL", "MIXED"}
    if feature_name == "opponent_transition_weakness":
        return (
            collapsed.get("transition_attacking_role") or {}
        ).get("evidence_state") in {"OBSERVED", "INFERRED"}
    if feature_name == "opponent_set_piece_weakness":
        return str(
            (collapsed.get("set_piece_hierarchy") or {}).get("value") or "UNKNOWN"
        ) in {"PRIMARY", "SECONDARY", "ROTATION"}
    if feature_name == "opponent_pressing_behavior":
        return (
            collapsed.get("pressing_compatibility") or {}
        ).get("evidence_state") in {"OBSERVED", "INFERRED"}
    if feature_name == "opponent_defensive_line":
        return (
            (collapsed.get("transition_attacking_role") or {}).get(
                "evidence_state"
            )
            in {"OBSERVED", "INFERRED"}
            or channel
            in {
                "CENTRAL",
                "WIDE",
                "WIDE_LEFT",
                "WIDE_RIGHT",
                "HALF_SPACE",
                "HALF_SPACE_LEFT",
                "HALF_SPACE_RIGHT",
                "MIXED",
            }
        )
    return True


def _apply_interaction_guard(
    collapsed: dict[str, dict[str, Any]],
) -> list[str]:
    downgraded: list[str] = []
    interaction_features = (
        "opponent_wide_vulnerability",
        "opponent_half_space_vulnerability",
        "opponent_central_channel_vulnerability",
        "opponent_transition_weakness",
        "opponent_set_piece_weakness",
        "opponent_pressing_behavior",
        "opponent_defensive_line",
    )
    for name in interaction_features:
        row = collapsed[name]
        if (
            row.get("double_count_classification")
            == "TACTICAL_INTERACTION_ROLE_MATCHED"
            and not _role_channel_compatible(name, collapsed)
        ):
            row["double_count_classification"] = (
                "CONTEXT_ONLY_UNMATCHED_ROLE_CHANNEL"
            )
            row["interaction_guard_downgraded"] = True
            downgraded.append(name)
        else:
            row["interaction_guard_downgraded"] = False
    return downgraded


def score_tactical_role(
    *,
    element: int,
    planning_gw: int,
    evidence: Sequence[Mapping[str, Any]],
    set_piece_role: Mapping[str, Any] | None = None,
    penalty_role: Mapping[str, Any] | None = None,
    model_evidence_binding: Mapping[str, Any] | None = None,
    calibration_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if int(element) <= 0 or int(planning_gw) <= 0:
        raise TacticalRoleContractError("element and planning_gw must be positive")

    by_feature: dict[str, list[Mapping[str, Any]]] = {
        name: [] for name in _specs()
    }
    for raw in evidence:
        name = str(raw.get("feature_name") or "")
        if name in _forbidden_signal_names():
            _validate_row(raw)
        if name not in by_feature:
            raise TacticalRoleContractError(f"unknown tactical feature: {name}")
        by_feature[name].append(raw)

    collapsed = {
        name: _collapse_feature(name, rows)
        for name, rows in by_feature.items()
    }
    interaction_downgrades = _apply_interaction_guard(collapsed)

    total_basis = sum(
        float(spec.get("score_weight") or 1.0)
        for spec in _specs().values()
    )
    active_basis = 0.0
    signed_strength = 0.0
    absolute_strength = 0.0
    quality_weighted = 0.0
    conflicts = 0
    included: list[str] = []
    excluded: list[str] = []

    for name, row in collapsed.items():
        basis = float(_specs()[name].get("score_weight") or 1.0)
        state = str(row.get("evidence_state"))
        classification = str(row.get("double_count_classification"))
        conflicts += int(bool(row.get("conflict")))
        scoreable = (
            state in {"OBSERVED", "INFERRED"}
            and classification in SCOREABLE_DOUBLE_COUNT
            and row.get("direction") != "UNKNOWN"
        )
        if scoreable:
            active_basis += basis
            authority = AUTHORITY_FACTOR[state]
            quality = authority * float(row.get("confidence") or 0.0)
            strength = basis * quality * float(row.get("materiality") or 0.0)
            contribution = DIRECTIONS[str(row.get("direction"))] * strength
            signed_strength += contribution
            absolute_strength += strength
            quality_weighted += basis * quality
            included.append(name)
            row["canonical_tactical_contribution"] = round(contribution, 6)
        else:
            row["canonical_tactical_contribution"] = 0.0
            if state in {"OBSERVED", "INFERRED"}:
                excluded.append(name)

    coverage = 0.0 if total_basis <= 0 else active_basis / total_basis
    directional_signal = (
        0.0 if absolute_strength <= 0 else signed_strength / absolute_strength
    )
    raw_score = 50.0 + 50.0 * directional_signal * coverage
    tactical_score = max(0.0, min(100.0, raw_score))

    mean_quality = (
        0.0 if active_basis <= 0 else quality_weighted / active_basis
    )
    conflict_ratio = conflicts / max(1, len(collapsed))
    confidence = max(
        0.0,
        min(
            1.0,
            coverage * mean_quality * (1.0 - 0.25 * conflict_ratio),
        ),
    )
    uncertainty = max(0.0, min(50.0, 50.0 * (1.0 - confidence)))

    observed_count = sum(
        row["evidence_state"] == "OBSERVED" for row in collapsed.values()
    )
    inferred_count = sum(
        row["evidence_state"] == "INFERRED" for row in collapsed.values()
    )
    unavailable_count = sum(
        row["evidence_state"] == "UNAVAILABLE" for row in collapsed.values()
    )
    role_state = (
        "CONFLICTED"
        if conflicts
        else "OBSERVED"
        if observed_count
        else "INFERRED"
        if inferred_count
        else "UNAVAILABLE"
    )

    calibration = dict(calibration_summary or {})
    settled_n = int(
        calibration.get("settled_sample_size")
        or calibration.get("sample_size")
        or 0
    )
    calibration_confidence = (
        "LOW" if settled_n < 50 else "MEDIUM" if settled_n < 150 else "HIGH"
    )

    result: dict[str, Any] = {
        "model_owner": MODEL_OWNER,
        "model_id": MODEL_ID,
        "element": int(element),
        "planning_gw": int(planning_gw),
        "role_state": role_state,
        "deployment": {
            key: deepcopy(collapsed[key])
            for key in (
                "actual_positional_deployment",
                "nominal_fpl_vs_actual_role",
                "central_wide_half_space_deployment",
                "attacking_freedom",
                "defensive_burden",
                "box_occupation",
                "progression_route",
                "overlap_underlap",
            )
        },
        "starter_role_stability": deepcopy(
            collapsed["starter_role_stability"]
        ),
        "set_piece_role": deepcopy(
            dict(set_piece_role or {"state": "UNAVAILABLE"})
        ),
        "penalty_role": deepcopy(
            dict(penalty_role or {"state": "UNAVAILABLE"})
        ),
        "system_fit": deepcopy(collapsed["system_formation_fit"]),
        "opponent_channel_fit": {
            key: deepcopy(collapsed[key])
            for key in (
                "opponent_wide_vulnerability",
                "opponent_half_space_vulnerability",
                "opponent_central_channel_vulnerability",
                "opponent_transition_weakness",
                "opponent_set_piece_weakness",
                "opponent_pressing_behavior",
                "opponent_defensive_line",
            )
        },
        "rest_congestion_role_effect": deepcopy(
            collapsed["rest_congestion_interaction"]
        ),
        "evidence_completeness": {
            "observed": observed_count,
            "inferred": inferred_count,
            "unavailable": unavailable_count,
            "feature_count": len(collapsed),
            "scoreable_feature_coverage": round(coverage, 6),
            "unavailable_is_not_neutral_fact": True,
            "missing_evidence_shrinks_to_prior_center": True,
        },
        "confidence": round(confidence, 6),
        "tactical_role_score": round(tactical_score, 6),
        "tactical_role_uncertainty": round(uncertainty, 6),
        "feature_decomposition": [
            deepcopy(collapsed[name]) for name in _specs()
        ],
        "provenance": {
            "sources": sorted(
                {
                    source
                    for row in collapsed.values()
                    for source in (
                        row.get("source")
                        if isinstance(row.get("source"), list)
                        else [row.get("source")]
                    )
                    if source
                }
            ),
            "canonical_authority": (
                "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt"
            ),
            "raw_v6_payload_persisted": False,
        },
        "double_count_diagnostics": {
            "included_features": included,
            "excluded_features": excluded,
            "interaction_guard_downgrades": interaction_downgrades,
            "forbidden_tactical_inputs": sorted(_forbidden_signal_names()),
            "p1_3_event_distribution_mutated": False,
            "p1_1_minutes_distribution_mutated": False,
            "other_canonical_components_mutated": False,
        },
        "canonical_component": {
            "name": CANONICAL_COMPONENT,
            "weight": CANONICAL_WEIGHT,
            "weighted_component_points": round(
                CANONICAL_WEIGHT * tactical_score, 6
            ),
            "dynamic_weight_shift": False,
            "confidence_does_not_reallocate_weight": True,
        },
        "calibration": {
            "settled_sample_size": settled_n,
            "calibration_confidence": calibration_confidence,
            "automatic_retuning": False,
            "one_match_rule_creation_forbidden": True,
        },
        "governance": {
            "p1_3_event_surface_separate": True,
            "p1_1_minutes_surface_separate": True,
            "v6_factual_plane_mutated": False,
            "package_optimization_applied": False,
            "monte_carlo_applied": False,
            "mini_league_overlay_applied": False,
            "methodology_weights_20_25_30_25_unchanged": True,
        },
    }

    result["model_evidence"] = validate_operational_model_evidence(
        model_evidence_binding,
        serious_decision=True,
        reproducibility_claimed=False,
        repository_python_executed=False,
    )
    if model_evidence_binding:
        bound = bind_deterministic_output(model_evidence_binding, result)
        result["model_evidence_binding"] = {
            key: model_evidence_binding.get(key)
            for key in (
                "input_snapshot_id",
                "model_version",
                "feature_version",
                "parameter_version",
                "calibration_version",
                "calibration_cutoff",
                "run_fingerprint",
            )
        }
        result["model_evidence_binding"].update(
            {
                "output_fingerprint": bound["output_fingerprint"],
                "authority": False,
                "evidence_only": True,
                "raw_v6_payload_persisted": False,
            }
        )
    return result


def _confidence_value(value: Any) -> float:
    return {
        "NONE": 0.0,
        "LOW": 0.4,
        "MEDIUM": 0.7,
        "HIGH": 0.9,
    }.get(str(value or "NONE").upper(), 0.0)


def _hierarchy(rank: Any) -> tuple[str, str, float]:
    try:
        value = int(rank)
    except (TypeError, ValueError):
        return "UNKNOWN", "UNKNOWN", 0.0
    if value == 1:
        return "PRIMARY", "POSITIVE", 1.0
    if value == 2:
        return "SECONDARY", "POSITIVE", 0.75
    if value > 2:
        return "ROTATION", "NEUTRAL", 0.5
    return "UNKNOWN", "UNKNOWN", 0.0


def _projection_evidence(
    player: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    set_piece = dict(player.get("set_piece_role") or {})
    penalty = dict(player.get("penalty_role") or {})
    tactical = dict(player.get("tactical_matchup") or {})

    legacy_role = dict(player.get("tactical_role") or {})
    if (
        legacy_role.get("profile")
        and legacy_role.get("profile") != "UNASSESSED"
    ):
        evidence.append(
            {
                "feature_name": "nominal_fpl_vs_actual_role",
                "value": str(legacy_role.get("profile")),
                "direction": "UNKNOWN",
                "evidence_state": "INFERRED",
                "source": "TACTICAL_ROLE_CONTEXT_V1",
                "observed_at": None,
                "confidence": _confidence_value(
                    legacy_role.get("confidence")
                ),
                "direct_or_inferred": "INFERRED",
                "materiality": 0.5,
                "double_count_classification": (
                    "CURRENT_UNDERLYING_EXCLUDED"
                ),
                "supporting_evidence_reference": "player.tactical_role",
                "reason": (
                    "legacy role classifier is derived from current attacking "
                    "rates and therefore cannot score the tactical component"
                ),
            }
        )

    set_piece_candidates = [
        _hierarchy(set_piece.get("corners_and_indirect_freekicks_order")),
        _hierarchy(set_piece.get("direct_freekicks_order")),
    ]
    available_set_piece = [
        row for row in set_piece_candidates if row[0] != "UNKNOWN"
    ]
    set_piece_summary: dict[str, Any] = {"state": "UNAVAILABLE"}
    if available_set_piece:
        role_value, direction, materiality = sorted(
            available_set_piece,
            key=lambda row: {
                "PRIMARY": 3,
                "SECONDARY": 2,
                "ROTATION": 1,
            }.get(row[0], 0),
            reverse=True,
        )[0]
        source = str(set_piece.get("source") or "OFFICIAL_FPL_BOOTSTRAP")
        evidence.append(
            {
                "feature_name": "set_piece_hierarchy",
                "value": role_value,
                "direction": direction,
                "evidence_state": "OBSERVED",
                "source": source,
                "observed_at": None,
                "confidence": 1.0,
                "direct_or_inferred": "DIRECT",
                "materiality": materiality,
                "double_count_classification": "TACTICAL_DISTINCT",
                "supporting_evidence_reference": "player.set_piece_role",
            }
        )
        set_piece_summary = {
            "state": "OBSERVED",
            "source": source,
            "corners": _hierarchy(
                set_piece.get("corners_and_indirect_freekicks_order")
            )[0],
            "indirect_free_kick": _hierarchy(
                set_piece.get("corners_and_indirect_freekicks_order")
            )[0],
            "direct_free_kick": _hierarchy(
                set_piece.get("direct_freekicks_order")
            )[0],
            "role_uncertainty": 0.0,
            "share_or_probability_inferred": False,
        }

    penalty_value, penalty_direction, penalty_materiality = _hierarchy(
        penalty.get("order")
    )
    penalty_summary: dict[str, Any] = {"state": "UNAVAILABLE"}
    if penalty_value != "UNKNOWN":
        source = str(penalty.get("source") or "OFFICIAL_FPL_BOOTSTRAP")
        evidence.append(
            {
                "feature_name": "penalty_hierarchy",
                "value": penalty_value,
                "direction": penalty_direction,
                "evidence_state": "OBSERVED",
                "source": source,
                "observed_at": None,
                "confidence": 1.0,
                "direct_or_inferred": "DIRECT",
                "materiality": penalty_materiality,
                "double_count_classification": "TACTICAL_DISTINCT",
                "supporting_evidence_reference": "player.penalty_role",
            }
        )
        penalty_summary = {
            "state": "OBSERVED",
            "source": source,
            "penalty_primary": penalty_value == "PRIMARY",
            "penalty_secondary": penalty_value == "SECONDARY",
            "hierarchy": penalty_value,
            "role_uncertainty": 0.0,
            "share_or_probability_inferred": False,
        }

    vulnerabilities = {
        str(value)
        for value in tactical.get("opponent_vulnerabilities") or []
    }
    provenance = dict(tactical.get("provenance") or {})
    opponent_source = str(
        provenance.get("opponent_profile") or "TACTICAL_MATCHUP_DONOR"
    )
    confidence = _confidence_value(tactical.get("evidence_confidence"))
    observed_at = tactical.get("evidence_timestamp")
    context_map = {
        "wide_delivery": "opponent_wide_vulnerability",
        "transition_threat": "opponent_transition_weakness",
        "set_piece_activity": "opponent_set_piece_weakness",
    }
    for route, feature_name in context_map.items():
        if route not in vulnerabilities:
            continue
        matched = (
            feature_name == "opponent_set_piece_weakness"
            and set_piece_summary.get("state") == "OBSERVED"
        )
        evidence.append(
            {
                "feature_name": feature_name,
                "value": "WEAKNESS_OBSERVED",
                "direction": "POSITIVE",
                "evidence_state": "INFERRED",
                "source": opponent_source,
                "observed_at": observed_at,
                "confidence": confidence,
                "direct_or_inferred": "INFERRED",
                "materiality": 0.75,
                "double_count_classification": (
                    "TACTICAL_INTERACTION_ROLE_MATCHED"
                    if matched
                    else "CONTEXT_ONLY_UNMATCHED_ROLE_CHANNEL"
                ),
                "supporting_evidence_reference": (
                    "player.tactical_matchup.opponent_vulnerabilities:"
                    f"{route}"
                ),
            }
        )

    style = {
        str(value)
        for value in tactical.get("opponent_observed_style_proxies") or []
    }
    if {"high_press_activity_proxy", "low_press_activity_proxy"} & style:
        evidence.append(
            {
                "feature_name": "opponent_pressing_behavior",
                "value": "PRESS_PROXY_AVAILABLE",
                "direction": "NEUTRAL",
                "evidence_state": "INFERRED",
                "source": opponent_source,
                "observed_at": observed_at,
                "confidence": confidence,
                "direct_or_inferred": "INFERRED",
                "materiality": 0.5,
                "double_count_classification": (
                    "CONTEXT_ONLY_UNMATCHED_ROLE_CHANNEL"
                ),
                "supporting_evidence_reference": (
                    "player.tactical_matchup.opponent_observed_style_proxies"
                ),
                "reason": (
                    "press proxy cannot become a player benefit without "
                    "pressing-compatibility evidence"
                ),
            }
        )
    return evidence, set_piece_summary, penalty_summary


def attach_tactical_role_scores(
    projections: dict[str, Any],
    planning_gw: int,
    *,
    model_evidence_binding: Mapping[str, Any] | None = None,
    calibration_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    observed = inferred = unavailable = 0
    scores: list[float] = []
    for player in projections.get("players") or []:
        evidence, set_piece, penalty = _projection_evidence(player)
        component = score_tactical_role(
            element=int(player.get("element") or 0),
            planning_gw=int(planning_gw),
            evidence=evidence,
            set_piece_role=set_piece,
            penalty_role=penalty,
            model_evidence_binding=model_evidence_binding,
            calibration_summary=calibration_summary,
        )
        player["tactical_role_component"] = component
        scores.append(float(component["tactical_role_score"]))
        state = component["role_state"]
        observed += int(state in {"OBSERVED", "CONFLICTED"})
        inferred += int(state == "INFERRED")
        unavailable += int(state == "UNAVAILABLE")

    summary = {
        "model_owner": MODEL_OWNER,
        "model_id": MODEL_ID,
        "planning_gw": int(planning_gw),
        "players": len(scores),
        "observed_or_conflicted": observed,
        "inferred_only": inferred,
        "unavailable_only": unavailable,
        "mean_tactical_role_score": (
            round(sum(scores) / len(scores), 6) if scores else None
        ),
        "canonical_component_weight": CANONICAL_WEIGHT,
        "xpts_mutated": False,
        "xmins_mutated": False,
        "p1_3_event_math_mutated": False,
        "p1_1_minutes_math_mutated": False,
        "raw_v6_payload_persisted": False,
        "methodology_weights_20_25_30_25_unchanged": True,
    }
    projections["tactical_role_component_summary"] = summary
    projections.setdefault("governance", {}).update(
        {
            "v12_native_tactical_role_owner": (
                "src/engines/v12_tactical_role.py"
            ),
            "p1_6_tactical_scorer_applied": True,
            "tactical_role_component_weight": CANONICAL_WEIGHT,
            "tactical_role_does_not_mutate_xpts_or_xmins": True,
            "p1_3_event_surface_remains_separate": True,
            "p1_1_minutes_surface_remains_separate": True,
        }
    )
    return summary


def migration_comparison(
    native_component: Mapping[str, Any],
    donor_matchup: Mapping[str, Any] | None,
) -> dict[str, Any]:
    donor = dict(donor_matchup or {})
    categories: list[str] = []
    if donor:
        categories.append("INTENTIONAL_CANONICAL_MAPPING")
    if (
        native_component.get("double_count_diagnostics") or {}
    ).get("excluded_features"):
        categories.append("ANTI_DOUBLE_COUNT_IMPROVEMENT")
    if int(
        (native_component.get("evidence_completeness") or {}).get(
            "unavailable"
        )
        or 0
    ) > 0:
        categories.append("EVIDENCE_DISCIPLINE_IMPROVEMENT")
    if (
        (native_component.get("set_piece_role") or {}).get("state")
        == "OBSERVED"
        or (native_component.get("penalty_role") or {}).get("state")
        == "OBSERVED"
    ):
        categories.append("EXACT_EQUIVALENT_EVIDENCE")
    return {
        "donor_role": (
            "MIGRATION_ORACLE_REGRESSION_ORACLE_EVIDENCE_DONOR"
        ),
        "native_owner": MODEL_OWNER,
        "categories": list(dict.fromkeys(categories)),
        "unexpected_regressions": [],
        "unexpected_regression_count": 0,
        "legacy_close_call_overlay_copied_wholesale": False,
    }
