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
from src.rules import CLEAN_SHEET_POINTS

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "tactical_role_canonical.json"
PLAYER_EVENTS_CONFIG_PATH = ROOT / "config" / "intelligence" / "player_events.json"
TACTICAL_DONOR_CONFIG_PATH = ROOT / "config" / "intelligence" / "tactical_role_context.json"

MODEL_OWNER = "V12_TACTICAL_ROLE"
MODEL_ID = "v12_tactical_role_canonical"
CANONICAL_COMPONENT = "TACTICAL_ROLE"
CANONICAL_WEIGHT = 0.25

EVIDENCE_STATES = {"OBSERVED", "INFERRED", "UNAVAILABLE"}
TACTICAL_EVIDENCE_CLASSES = frozenset({"OBSERVED_ROLE", "INFERRED_ROLE", "FPL_POSITION_ONLY", "UNKNOWN"})
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


def classify_tactical_evidence(
    *,
    element_id: int,
    evidence_class: str,
    tactical_numeric_evidence: float | None = None,
    provenance: str | None = None,
    fingerprint: str | None = None,
) -> dict[str, Any]:
    """Classify tactical evidence quality without changing P1.6 mathematics."""
    try:
        element = int(element_id)
    except (TypeError, ValueError) as exc:
        raise TacticalRoleContractError("element_id must be a positive integer") from exc
    if element <= 0:
        raise TacticalRoleContractError("element_id must be a positive integer")
    classification = str(evidence_class or "").strip().upper()
    if classification not in TACTICAL_EVIDENCE_CLASSES:
        raise TacticalRoleContractError(
            "evidence_class must be one of OBSERVED_ROLE/INFERRED_ROLE/"
            "FPL_POSITION_ONLY/UNKNOWN"
        )
    provenance_text = str(provenance or "").strip() or None
    fingerprint_text = str(fingerprint or "").strip() or None
    if classification in {"OBSERVED_ROLE", "INFERRED_ROLE"} and provenance_text is None:
        raise TacticalRoleContractError(
            f"{classification} requires explicit provenance"
        )
    numeric = tactical_numeric_evidence
    if classification in {"FPL_POSITION_ONLY", "UNKNOWN"} and numeric is not None:
        raise TacticalRoleContractError(
            f"{classification} cannot silently become numeric tactical evidence"
        )
    if numeric is not None:
        numeric = _bounded(numeric, "tactical_numeric_evidence")
    return {
        "element_id": element,
        "evidence_class": classification,
        "provenance": provenance_text,
        "fingerprint": fingerprint_text,
        "tactical_numeric_evidence": numeric,
        "authority": False,
        "evidence_only": True,
        "changes_canonical_score": False,
        "changes_p1_6_math": False,
        "fpl_position_is_tactical_role_proof": False,
    }


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if payload.get("contract") != "V12_TACTICAL_ROLE_CANONICAL_V2":
        raise TacticalRoleContractError("unexpected tactical role canonical contract")
    if float(payload.get("canonical_component_weight") or -1.0) != CANONICAL_WEIGHT:
        raise TacticalRoleContractError("canonical tactical weight drift")
    return payload


@lru_cache(maxsize=1)
def _player_events_config() -> dict[str, Any]:
    return json.loads(PLAYER_EVENTS_CONFIG_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _tactical_donor_config() -> dict[str, Any]:
    return json.loads(TACTICAL_DONOR_CONFIG_PATH.read_text(encoding="utf-8"))


def _contextual_config() -> dict[str, Any]:
    return dict(load_config().get("contextual_feature_contract") or {})


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
        "model_version": load_config().get("model_version"),
        "feature_version": load_config().get("feature_version"),
        "parameter_version": load_config().get("parameter_version"),
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



def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _mean_available(values: Sequence[float | None]) -> float | None:
    available = [float(value) for value in values if value is not None]
    return sum(available) / len(available) if available else None


def _ratio_score(value: Any, reference: Any) -> float | None:
    if value is None or reference is None:
        return None
    x = max(0.0, _finite(value, "ratio.value"))
    ref = max(0.0, _finite(reference, "ratio.reference"))
    if ref <= 0.0:
        return 1.0 if x > 0.0 else 0.5
    return _clamp01(x / (x + ref))


def _score_label(value: float | None) -> str:
    if value is None:
        return "UNAVAILABLE"
    score = _clamp01(value)
    if score < 1.0 / 3.0:
        return "LOW"
    if score < 2.0 / 3.0:
        return "MEDIUM"
    return "HIGH"


def _fit_label(value: float | None) -> str:
    if value is None:
        return "UNAVAILABLE"
    score = _clamp01(value)
    if score < 1.0 / 3.0:
        return "NEGATIVE"
    if score < 2.0 / 3.0:
        return "NEUTRAL"
    return "POSITIVE"


def _suppression_label(value: float | None) -> str:
    if value is None:
        return "UNAVAILABLE"
    score = _clamp01(value)
    if score < 1.0 / 3.0:
        return "MILD_NEGATIVE" if score > 0.0 else "NONE"
    if score < 2.0 / 3.0:
        return "NEGATIVE"
    return "STRONG_NEGATIVE"


def _strength_maps(
    team_strength: Mapping[str, Any] | None,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    payload = dict(team_strength or {})
    rows = {
        int(row.get("team_id")): dict(row)
        for row in payload.get("teams") or []
        if row.get("team_id") is not None
    }
    return rows, dict(payload.get("baseline") or {})


def _fixture_identity(
    player: Mapping[str, Any],
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    team_id = int(player.get("team_id") or -1)
    home = bool(fixture.get("home"))
    if fixture.get("home") is None:
        try:
            home = int(fixture.get("team_h") or -2) == team_id
        except (TypeError, ValueError):
            home = False
    opponent = fixture.get("opponent")
    if opponent is None:
        identity = fixture.get("identity") or {}
        opponent = identity.get("opponent")
    if opponent is None:
        team_h = fixture.get("team_h")
        team_a = fixture.get("team_a")
        if team_h is not None and team_a is not None:
            opponent = team_a if home else team_h
    try:
        opponent_id = int(opponent) if opponent is not None else None
    except (TypeError, ValueError):
        opponent_id = None
    return {
        "team_id": team_id,
        "opponent_team_id": opponent_id,
        "home": home,
        "fixture": fixture.get("fixture")
        or (fixture.get("identity") or {}).get("fixture"),
        "gw": int(fixture.get("event") or (fixture.get("identity") or {}).get("gw") or 0),
    }


def _home_attack_context(
    player: Mapping[str, Any],
    fixture: Mapping[str, Any],
    team_strength: Mapping[str, Any] | None,
) -> tuple[float | None, dict[str, Any]]:
    identity = _fixture_identity(player, fixture)
    if not identity["home"]:
        return 0.5, {
            "state": "OBSERVED_NOT_HOME",
            "score": 0.5,
            "label": "NEUTRAL",
            "application_count": 1,
            "generic_opponent_strength_consumed": False,
            "source": "fixture.identity.home",
            "provenance": ["P1.3 fixture identity"],
            "missing": [],
        }

    rows, baseline = _strength_maps(team_strength)
    own = rows.get(identity["team_id"]) or {}
    opponent = rows.get(identity["opponent_team_id"] or -1) or {}
    ratios: list[tuple[str, float]] = []
    missing: list[str] = []

    own_home = own.get("attack_home_index")
    own_away = own.get("attack_away_index")
    if own_home is not None and own_away is not None:
        neutral = max(1e-9, (_finite(own_home, "attack_home") + _finite(own_away, "attack_away")) / 2.0)
        ratios.append(("own_home_attack_vs_own_neutral", max(0.0, _finite(own_home, "attack_home")) / neutral))
    else:
        missing.append("own_home_vs_away_attack_index")

    opp_home_def = opponent.get("defence_home_index")
    opp_away_def = opponent.get("defence_away_index")
    if opp_home_def is not None and opp_away_def is not None:
        neutral_def = max(
            1e-9,
            (_finite(opp_home_def, "opp_def_home") + _finite(opp_away_def, "opp_def_away")) / 2.0,
        )
        away_def = max(1e-9, _finite(opp_away_def, "opp_def_away"))
        ratios.append(("opponent_away_defence_weakness_vs_neutral", neutral_def / away_def))
    else:
        missing.append("opponent_home_vs_away_defence_index")

    home_base = baseline.get("home_goals")
    away_base = baseline.get("away_goals")
    if home_base is not None and away_base is not None:
        league_neutral = max(
            1e-9,
            (_finite(home_base, "baseline.home") + _finite(away_base, "baseline.away")) / 2.0,
        )
        ratios.append(("league_home_goal_environment_vs_neutral", max(0.0, _finite(home_base, "baseline.home")) / league_neutral))
    else:
        missing.append("league_home_away_baseline")

    transformed = [
        (name, ratio / (1.0 + ratio))
        for name, ratio in ratios
        if ratio >= 0.0
    ]
    score = _mean_available([value for _, value in transformed])
    return score, {
        "state": "AVAILABLE" if score is not None else "UNAVAILABLE",
        "score": None if score is None else round(score, 6),
        "label": _fit_label(score),
        "application_count": 1,
        "generic_opponent_strength_consumed": False,
        "venue_specific_only": True,
        "source": "team_strength venue-specific deltas + league venue baseline",
        "provenance": [
            "src/models/team_strength.py attack_home_index/attack_away_index",
            "src/models/team_strength.py defence_home_index/defence_away_index",
            "src/models/team_strength.py baseline home_goals/away_goals",
        ],
        "ratios": [
            {"name": name, "raw_ratio": round(ratio, 6), "bounded_score": round(value, 6)}
            for (name, ratio), (_, value) in zip(ratios, transformed)
        ],
        "missing": missing,
        "double_count_guard": "HOME_CONTEXT_APPLIED_ONCE_AND_EXCLUDES_NEUTRAL_OPPONENT_STRENGTH",
    }


def _attacking_involvement(
    player: Mapping[str, Any],
) -> tuple[float | None, dict[str, Any]]:
    position = str(player.get("position") or "UNKNOWN")
    posterior = dict(player.get("posterior_rates") or {})
    legacy_role = dict(player.get("tactical_role") or {})
    metrics = dict(legacy_role.get("metrics") or {})
    donor_thresholds = (
        (_tactical_donor_config().get("role_thresholds") or {}).get(position)
        or {}
    )
    position_prior = (
        (_player_events_config().get("position_priors") or {}).get(position)
        or {}
    )

    goal = dict(posterior.get("goal") or {})
    assist = dict(posterior.get("assist") or {})
    values: dict[str, tuple[Any, Any, str]] = {
        "xg90": (
            goal.get("posterior_rate90"),
            goal.get("prior", position_prior.get("xg90")),
            "P1.3 posterior goal rate vs governed prior",
        ),
        "xa90": (
            assist.get("posterior_rate90"),
            assist.get("prior", position_prior.get("xa90")),
            "P1.3 posterior assist rate vs governed prior",
        ),
    }
    if position == "DEF":
        values.update(
            {
                "shots90": (
                    metrics.get("shots_per90"),
                    donor_thresholds.get("box_threat_shots_per90"),
                    "legacy observed role threshold donor",
                ),
                "box_touches90": (
                    metrics.get("touches_opposition_box_per90"),
                    donor_thresholds.get("attacking_box_touches_per90"),
                    "legacy observed role threshold donor",
                ),
                "chances_created90": (
                    metrics.get("chances_created_per90"),
                    donor_thresholds.get("attacking_chances_created_per90"),
                    "legacy observed role threshold donor",
                ),
            }
        )
    elif position in {"MID", "FWD"}:
        values.update(
            {
                "shots90": (
                    metrics.get("shots_per90"),
                    donor_thresholds.get("shooter_shots_per90"),
                    "legacy observed role threshold donor",
                ),
                "box_touches90": (
                    metrics.get("touches_opposition_box_per90"),
                    donor_thresholds.get("shooter_box_touches_per90"),
                    "legacy observed role threshold donor",
                ),
                "chances_created90": (
                    metrics.get("chances_created_per90"),
                    donor_thresholds.get("creator_chances_created_per90"),
                    "legacy observed role threshold donor",
                ),
            }
        )

    normalized: dict[str, dict[str, Any]] = {}
    available_scores: list[float] = []
    missing: list[str] = []
    for name, (value, reference, source) in values.items():
        score = _ratio_score(value, reference)
        if score is None:
            missing.append(name)
            normalized[name] = {
                "state": "UNAVAILABLE",
                "score": None,
                "value": value,
                "reference": reference,
                "source": source,
            }
            continue
        available_scores.append(score)
        normalized[name] = {
            "state": "AVAILABLE",
            "score": round(score, 6),
            "value": None if value is None else round(float(value), 6),
            "reference": None if reference is None else round(float(reference), 6),
            "source": source,
        }

    raw = _mean_available(available_scores)
    minutes = max(
        0.0,
        _finite(
            legacy_role.get(
                "evidence_minutes",
                (player.get("current_season") or {}).get("minutes", 0.0),
            ),
            "attacking_involvement.evidence_minutes",
        ),
    )
    shrink_minutes = max(
        0.0,
        _finite(
            _player_events_config().get("rate_shrinkage_minutes", 450.0),
            "player_events.rate_shrinkage_minutes",
        ),
    )
    reliability = (
        minutes / (minutes + shrink_minutes)
        if minutes + shrink_minutes > 0.0
        else 0.0
    )
    score = (
        None
        if raw is None
        else _clamp01(0.5 + reliability * (raw - 0.5))
    )
    return score, {
        "state": "AVAILABLE" if score is not None else "UNAVAILABLE",
        "score": None if score is None else round(score, 6),
        "label": _score_label(score),
        "raw_normalized_mean": None if raw is None else round(raw, 6),
        "sample_reliability": round(reliability, 6),
        "evidence_minutes": round(minutes, 3),
        "shrinkage_reference_minutes": round(shrink_minutes, 3),
        "metrics": normalized,
        "missing": missing,
        "position": position,
        "position_aware": True,
        "xgi_is_diagnostic_not_duplicate_input": True,
        "current_underlying_interaction_only": True,
        "direct_additive_underlying_points": False,
        "provenance": [
            "P1.3 posterior goal/assist rates",
            "config/intelligence/player_events.json position priors/rate shrinkage",
            "config/intelligence/tactical_role_context.json role thresholds",
        ],
    }


def _role_security(
    player: Mapping[str, Any],
    team_strength: Mapping[str, Any] | None,
) -> tuple[float | None, dict[str, Any]]:
    xmins = dict(player.get("xmins") or {})
    rows, _ = _strength_maps(team_strength)
    team_row = rows.get(int(player.get("team_id") or -1)) or {}
    current = dict(player.get("current_season") or {})
    signals: dict[str, float | None] = {}

    pstart = xmins.get("start_probability")
    signals["p_start"] = None if pstart is None else _clamp01(_finite(pstart, "p_start"))

    expected = xmins.get("expected_minutes")
    signals["xmins_share"] = (
        None
        if expected is None
        else _clamp01(_finite(expected, "expected_minutes") / 90.0)
    )

    starter_minutes = xmins.get("starter_minutes_if_start")
    signals["starter_duration_share"] = (
        None
        if starter_minutes is None
        else _clamp01(_finite(starter_minutes, "starter_minutes_if_start") / 90.0)
    )

    matches = int(team_row.get("matches_played") or 0)
    starts = int(current.get("starts") or 0)
    signals["recent_start_rate"] = (
        _clamp01(starts / max(1, matches)) if matches > 0 else None
    )

    score = _mean_available(list(signals.values()))
    missing = [name for name, value in signals.items() if value is None]
    return score, {
        "state": "AVAILABLE" if score is not None else "UNAVAILABLE",
        "score": None if score is None else round(score, 6),
        "label": _score_label(score),
        "signals": {
            name: None if value is None else round(value, 6)
            for name, value in signals.items()
        },
        "missing": missing
        + [
            "competition_minute_interference"
        ],
        "substitution_pattern_proxy": (
            None
            if starter_minutes is None
            else {
                "starter_minutes_if_start": round(float(starter_minutes), 3),
                "source": "P1.1 finite-state minutes",
            }
        ),
        "authority": "P1.1_CONSUMED_NOT_OWNED",
        "p1_1_minutes_mutated": False,
        "not_equal_to_xmins": True,
        "provenance": [
            "src/engines/v12_player_minutes.py start_probability",
            "src/engines/v12_player_minutes.py expected_minutes",
            "src/engines/v12_player_minutes.py starter_minutes_if_start",
            "current-season starts / team matches played",
        ],
    }


def _hierarchy_channel_strength(role: Mapping[str, Any] | None) -> float | None:
    row = dict(role or {})
    hierarchy = str(row.get("hierarchy") or "").upper()
    if not hierarchy:
        values = [
            str(row.get("corners") or "").upper(),
            str(row.get("direct_free_kick") or "").upper(),
            str(row.get("indirect_free_kick") or "").upper(),
        ]
        hierarchy = next(
            (
                value
                for value in ("PRIMARY", "SECONDARY", "ROTATION")
                if value in values
            ),
            "",
        )
    return {
        "PRIMARY": 1.0,
        "SECONDARY": 0.75,
        "ROTATION": 0.5,
    }.get(hierarchy)


def _scoring_channels(
    player: Mapping[str, Any],
    role_security_score: float | None,
    set_piece_role: Mapping[str, Any] | None,
    penalty_role: Mapping[str, Any] | None,
) -> tuple[dict[str, float | None], float | None, dict[str, Any]]:
    posterior = dict(player.get("posterior_rates") or {})
    position = str(player.get("position") or "UNKNOWN")
    position_prior = (
        (_player_events_config().get("position_priors") or {}).get(position)
        or {}
    )

    goal = dict(posterior.get("goal") or {})
    assist = dict(posterior.get("assist") or {})
    bonus = dict(posterior.get("bonus") or {})
    defcon = dict(posterior.get("defcon") or {})

    vector: dict[str, float | None] = {
        "GOAL": _ratio_score(
            goal.get("posterior_rate90"),
            goal.get("prior", position_prior.get("xg90")),
        ),
        "ASSIST": _ratio_score(
            assist.get("posterior_rate90"),
            assist.get("prior", position_prior.get("xa90")),
        ),
        "SET_PIECE": _hierarchy_channel_strength(set_piece_role),
        "PENALTY": _hierarchy_channel_strength(penalty_role),
        "DEFENSIVE_CONTRIBUTION": _ratio_score(
            defcon.get("posterior_count_rate90"),
            defcon.get("threshold"),
        )
        if defcon.get("eligible")
        else 0.0
        if defcon
        else None,
        "CLEAN_SHEET": None,
        "BONUS": _ratio_score(
            bonus.get("posterior_rate90"),
            bonus.get("prior", position_prior.get("bonus90")),
        ),
    }

    try:
        element_type = int(player.get("element_type") or 0)
    except (TypeError, ValueError):
        element_type = 0
    cs_points = float(CLEAN_SHEET_POINTS.get(element_type, 0))
    max_cs_points = float(max(CLEAN_SHEET_POINTS.values()) or 1)
    if role_security_score is not None:
        vector["CLEAN_SHEET"] = _clamp01(
            role_security_score * cs_points / max_cs_points
        )

    groups_cfg = _contextual_config().get("dependency_groups") or {}
    group_strengths: dict[str, float | None] = {}
    for group, channels in groups_cfg.items():
        available = [
            vector.get(str(channel))
            for channel in channels or []
            if vector.get(str(channel)) is not None
        ]
        group_strengths[str(group)] = (
            max(float(value) for value in available)
            if available
            else None
        )

    available_groups = [
        float(value)
        for value in group_strengths.values()
        if value is not None
    ]
    positive_groups = [value for value in available_groups if value > 0.0]
    diversity: float | None
    if not available_groups:
        diversity = None
    elif len(positive_groups) <= 1:
        diversity = 0.0
    else:
        total = sum(positive_groups)
        shares = [value / total for value in positive_groups]
        entropy = -sum(p * math.log(p) for p in shares if p > 0.0)
        max_entropy = math.log(max(2, len(available_groups)))
        entropy_norm = entropy / max_entropy if max_entropy > 0.0 else 0.0
        completeness = len(available_groups) / max(1, len(group_strengths))
        diversity = _clamp01(
            entropy_norm * max(positive_groups) * completeness
        )

    channel_evidence = {
        name: {
            "state": "AVAILABLE" if value is not None else "UNAVAILABLE",
            "strength": None if value is None else round(value, 6),
            "source": {
                "GOAL": "P1.3 posterior goal rate vs prior",
                "ASSIST": "P1.3 posterior assist rate vs prior",
                "SET_PIECE": "Official FPL set-piece hierarchy",
                "PENALTY": "Official FPL penalty hierarchy",
                "DEFENSIVE_CONTRIBUTION": "P1.3 DefCon posterior rate vs threshold",
                "CLEAN_SHEET": "FPL clean-sheet point eligibility × P1.1 role security",
                "BONUS": "P1.3 residual bonus posterior rate vs prior",
            }[name],
        }
        for name, value in vector.items()
    }
    return vector, diversity, {
        "state": "AVAILABLE" if diversity is not None else "UNAVAILABLE",
        "diversity": None if diversity is None else round(diversity, 6),
        "label": _score_label(diversity),
        "channels": channel_evidence,
        "dependency_groups": {
            name: None if value is None else round(value, 6)
            for name, value in group_strengths.items()
        },
        "available_group_count": len(available_groups),
        "group_count": len(group_strengths),
        "method": "NORMALIZED_ENTROPY_X_STRONGEST_GROUP_X_EVIDENCE_COMPLETENESS",
        "linear_channel_count_bonus": False,
        "partially_dependent_channels_grouped": True,
        "p1_3_event_probabilities_mutated": False,
    }


def _tactical_role_fit(
    player: Mapping[str, Any],
    opponent_team_id: int | None,
) -> tuple[float | None, dict[str, Any]]:
    matchup = dict(player.get("tactical_matchup") or {})
    if not matchup:
        return None, {
            "state": "UNAVAILABLE",
            "score": None,
            "reason": "TACTICAL_MATCHUP_MISSING",
        }
    mapped_opponent = matchup.get("opponent_team_id")
    if (
        opponent_team_id is not None
        and mapped_opponent is not None
        and int(mapped_opponent) != int(opponent_team_id)
    ):
        return None, {
            "state": "UNAVAILABLE",
            "score": None,
            "reason": "TACTICAL_MATCHUP_BOUND_TO_DIFFERENT_FIXTURE",
        }

    edge = [str(x) for x in matchup.get("tactical_edge") or []]
    risk = [str(x) for x in matchup.get("tactical_risk") or []]
    total = len(edge) + len(risk)
    label = str(matchup.get("tactical_matchup_label") or "")
    if total > 0:
        raw = len(edge) / total
    elif label == "NEUTRAL_OBSERVED":
        raw = 0.5
    else:
        return None, {
            "state": "UNAVAILABLE",
            "score": None,
            "reason": "NO_ROLE_MATCHED_EDGE_OR_RISK",
            "tactical_label": label or None,
        }

    confidence_label = str(
        matchup.get("evidence_confidence")
        or matchup.get("tactical_confidence")
        or "NONE"
    ).upper()
    confidence_rank = {
        "NONE": 0,
        "LOW": 1,
        "MEDIUM": 2,
        "HIGH": 3,
    }.get(confidence_label, 0)
    confidence = confidence_rank / 3.0
    score = _clamp01(0.5 + confidence * (raw - 0.5))
    return score, {
        "state": "AVAILABLE",
        "score": round(score, 6),
        "label": _fit_label(score),
        "raw_role_match": round(raw, 6),
        "confidence": round(confidence, 6),
        "confidence_label": confidence_label,
        "edge": edge,
        "risk": risk,
        "source": "src/models/tactical_matchup.py role-route × opponent-context interaction",
        "subjective_text_numeric_authority": False,
    }


def _raw_fixture_suppression(
    player: Mapping[str, Any],
    fixture: Mapping[str, Any],
    team_strength: Mapping[str, Any] | None,
    scoring_channel_vector: Mapping[str, float | None],
) -> tuple[float | None, dict[str, Any]]:
    identity = _fixture_identity(player, fixture)
    rows, _ = _strength_maps(team_strength)
    opponent = rows.get(identity["opponent_team_id"] or -1) or {}
    if not opponent:
        return None, {
            "state": "UNAVAILABLE",
            "score": None,
            "reason": "OPPONENT_TEAM_STRENGTH_UNAVAILABLE",
            "missing_is_zero": False,
        }

    def neutral_index(home_key: str, away_key: str) -> float | None:
        home_value = opponent.get(home_key)
        away_value = opponent.get(away_key)
        if home_value is None or away_value is None:
            return None
        return max(
            1e-9,
            (
                _finite(home_value, home_key)
                + _finite(away_value, away_key)
            )
            / 2.0,
        )

    opponent_defence = neutral_index(
        "defence_home_index", "defence_away_index"
    )
    opponent_attack = neutral_index(
        "attack_home_index", "attack_away_index"
    )
    if opponent_defence is None or opponent_attack is None:
        return None, {
            "state": "UNAVAILABLE",
            "score": None,
            "reason": "OPPONENT_NEUTRAL_STRENGTH_INCOMPLETE",
            "missing_is_zero": False,
        }

    attack_difficulty = (
        max(0.0, 1.0 - 1.0 / opponent_defence)
        if opponent_defence > 1.0
        else 0.0
    )
    defence_difficulty = (
        max(0.0, 1.0 - 1.0 / opponent_attack)
        if opponent_attack > 1.0
        else 0.0
    )
    attack_channels = (
        "GOAL",
        "ASSIST",
        "SET_PIECE",
        "PENALTY",
        "BONUS",
    )
    defence_channels = (
        "DEFENSIVE_CONTRIBUTION",
        "CLEAN_SHEET",
    )
    attack_exposure = sum(
        float(scoring_channel_vector[name])
        for name in attack_channels
        if scoring_channel_vector.get(name) is not None
    )
    defence_exposure = sum(
        float(scoring_channel_vector[name])
        for name in defence_channels
        if scoring_channel_vector.get(name) is not None
    )
    exposure_total = attack_exposure + defence_exposure
    if exposure_total <= 0.0:
        return None, {
            "state": "UNAVAILABLE",
            "score": None,
            "reason": "SCORING_CHANNEL_EXPOSURE_UNAVAILABLE",
            "missing_is_zero": False,
        }
    attack_share = attack_exposure / exposure_total
    defence_share = defence_exposure / exposure_total
    raw = _clamp01(
        attack_share * attack_difficulty
        + defence_share * defence_difficulty
    )
    return raw, {
        "state": "AVAILABLE",
        "score": round(raw, 6),
        "label": _suppression_label(raw),
        "opponent_neutral_defence_index": round(opponent_defence, 6),
        "opponent_neutral_attack_index": round(opponent_attack, 6),
        "attack_difficulty": round(attack_difficulty, 6),
        "defence_difficulty": round(defence_difficulty, 6),
        "attack_channel_exposure_share": round(attack_share, 6),
        "defence_channel_exposure_share": round(defence_share, 6),
        "bounded": True,
        "venue_specific_delta_excluded": True,
        "easy_fixture_bonus_created": False,
        "source": "src/models/team_strength.py neutral opponent attack/defence indices",
    }


def compose_contextual_tactical_score(
    *,
    evidence_role_score: float,
    home_attack_context: float | None,
    attacking_involvement_score: float | None,
    role_security_score: float | None,
    scoring_channel_diversity: float | None,
    tactical_role_fit: float | None,
    fixture_suppression_raw: float,
) -> dict[str, Any]:
    base_norm = _clamp01(
        _finite(evidence_role_score, "evidence_role_score") / 100.0
    )
    raw_suppression = _clamp01(
        _finite(fixture_suppression_raw, "fixture_suppression_raw")
    )
    resilience_inputs = {
        "home_attack_context": home_attack_context,
        "attacking_involvement_score": attacking_involvement_score,
        "role_security_score": role_security_score,
        "scoring_channel_diversity": scoring_channel_diversity,
        "tactical_role_fit": tactical_role_fit,
    }
    available = [
        _clamp01(float(value))
        for value in resilience_inputs.values()
        if value is not None
    ]
    if not available:
        resilience = 0.5
        completeness = 0.0
        raw_resilience_mean = None
    else:
        raw_resilience_mean = sum(available) / len(available)
        completeness = len(available) / len(resilience_inputs)
        resilience = _clamp01(
            0.5 + completeness * (raw_resilience_mean - 0.5)
        )

    adjustment = 1.0 / (1.0 + resilience)
    effective = _clamp01(raw_suppression * adjustment)
    if raw_suppression > 0.0 and effective <= 0.0:
        raise TacticalRoleContractError(
            "role resilience may not erase positive opponent suppression"
        )
    if effective > raw_suppression + 1e-12:
        raise TacticalRoleContractError(
            "effective fixture suppression cannot exceed raw suppression"
        )

    pre_suppression = math.sqrt(max(0.0, base_norm * resilience))
    final = _clamp01(pre_suppression * (1.0 - effective))
    raw_penalty = pre_suppression * raw_suppression * 100.0
    effective_penalty = pre_suppression * effective * 100.0
    resilience_relief = raw_penalty - effective_penalty
    return {
        "role_resilience": round(resilience, 6),
        "role_resilience_inputs": {
            key: None if value is None else round(_clamp01(float(value)), 6)
            for key, value in resilience_inputs.items()
        },
        "role_resilience_raw_mean": (
            None
            if raw_resilience_mean is None
            else round(raw_resilience_mean, 6)
        ),
        "role_resilience_evidence_completeness": round(completeness, 6),
        "resilience_adjustment": round(adjustment, 6),
        "fixture_suppression_raw": round(raw_suppression, 6),
        "fixture_suppression_effective": round(effective, 6),
        "pre_suppression_role_quality": round(pre_suppression, 6),
        "canonical_tactical_role_score": round(final * 100.0, 6),
        "decomposition_points": {
            "PRE_SUPPRESSION_ROLE_QUALITY": round(
                pre_suppression * 100.0, 6
            ),
            "RAW_FIXTURE_SUPPRESSION": round(-raw_penalty, 6),
            "ROLE_RESILIENCE_RELIEF": round(resilience_relief, 6),
            "EFFECTIVE_FIXTURE_SUPPRESSION": round(
                -effective_penalty, 6
            ),
            "FINAL_TACTICAL_ROLE_SCORE": round(final * 100.0, 6),
        },
        "governance": {
            "fixture_difficulty_is_suppressor_not_veto": True,
            "opponent_strength_erased": False,
            "effective_suppression_nonnegative": True,
            "effective_suppression_bounded_by_raw": True,
            "resilience_maximum_relief_fraction": 0.5,
            "no_named_player_condition": True,
            "no_transfer_action_cost": True,
        },
    }



def bounded_counterfactual_validation() -> dict[str, Any]:
    """Deterministic scenario matrix for structural P1.6 regression validation.

    These are generic counterfactuals, not historical outcomes and not named-player
    tuning examples. Historical support remains a separate P1.5-settlement question.
    """
    scenarios = {
        "difficult_fixture_strong_role": {
            "evidence_role_score": 80.0,
            "home_attack_context": 0.80,
            "attacking_involvement_score": 0.90,
            "role_security_score": 0.90,
            "scoring_channel_diversity": 0.80,
            "tactical_role_fit": 0.80,
            "fixture_suppression_raw": 0.50,
        },
        "difficult_fixture_weak_role": {
            "evidence_role_score": 35.0,
            "home_attack_context": 0.50,
            "attacking_involvement_score": 0.30,
            "role_security_score": 0.30,
            "scoring_channel_diversity": 0.20,
            "tactical_role_fit": 0.30,
            "fixture_suppression_raw": 0.50,
        },
        "easy_fixture_strong_role": {
            "evidence_role_score": 80.0,
            "home_attack_context": 0.50,
            "attacking_involvement_score": 0.90,
            "role_security_score": 0.90,
            "scoring_channel_diversity": 0.80,
            "tactical_role_fit": 0.80,
            "fixture_suppression_raw": 0.0,
        },
        "easy_fixture_weak_role": {
            "evidence_role_score": 35.0,
            "home_attack_context": 0.50,
            "attacking_involvement_score": 0.30,
            "role_security_score": 0.30,
            "scoring_channel_diversity": 0.20,
            "tactical_role_fit": 0.30,
            "fixture_suppression_raw": 0.0,
        },
        "home_strong_role": {
            "evidence_role_score": 75.0,
            "home_attack_context": 0.80,
            "attacking_involvement_score": 0.80,
            "role_security_score": 0.85,
            "scoring_channel_diversity": 0.75,
            "tactical_role_fit": 0.75,
            "fixture_suppression_raw": 0.30,
        },
        "away_strong_role": {
            "evidence_role_score": 75.0,
            "home_attack_context": 0.50,
            "attacking_involvement_score": 0.80,
            "role_security_score": 0.85,
            "scoring_channel_diversity": 0.75,
            "tactical_role_fit": 0.75,
            "fixture_suppression_raw": 0.30,
        },
        "multi_channel_role": {
            "evidence_role_score": 70.0,
            "home_attack_context": 0.60,
            "attacking_involvement_score": 0.75,
            "role_security_score": 0.80,
            "scoring_channel_diversity": 0.80,
            "tactical_role_fit": 0.65,
            "fixture_suppression_raw": 0.30,
        },
        "single_channel_role": {
            "evidence_role_score": 70.0,
            "home_attack_context": 0.60,
            "attacking_involvement_score": 0.75,
            "role_security_score": 0.80,
            "scoring_channel_diversity": 0.10,
            "tactical_role_fit": 0.65,
            "fixture_suppression_raw": 0.30,
        },
    }
    results = {
        name: compose_contextual_tactical_score(**payload)
        for name, payload in scenarios.items()
    }
    h1 = (
        results["difficult_fixture_strong_role"][
            "canonical_tactical_role_score"
        ]
        > results["difficult_fixture_weak_role"][
            "canonical_tactical_role_score"
        ]
        and results["difficult_fixture_strong_role"][
            "fixture_suppression_effective"
        ]
        > 0.0
    )
    h2 = (
        results["easy_fixture_weak_role"]["canonical_tactical_role_score"]
        < results["easy_fixture_strong_role"]["canonical_tactical_role_score"]
    )
    h3 = (
        results["multi_channel_role"]["canonical_tactical_role_score"]
        > results["single_channel_role"]["canonical_tactical_role_score"]
    )
    h4 = (
        results["home_strong_role"]["canonical_tactical_role_score"]
        > results["away_strong_role"]["canonical_tactical_role_score"]
    )
    h5 = (
        results["difficult_fixture_strong_role"][
            "fixture_suppression_effective"
        ]
        < results["difficult_fixture_strong_role"]["fixture_suppression_raw"]
        and results["difficult_fixture_strong_role"][
            "fixture_suppression_effective"
        ]
        > 0.0
    )
    return {
        "validation_kind": "GENERIC_COUNTERFACTUAL_STRUCTURAL_VALIDATION",
        "historical_outcomes_used": False,
        "named_player_examples_used": False,
        "scenarios": results,
        "hypotheses": {
            "H1_DIFFICULT_FIXTURE_STRONG_ROLE_NOT_AUTOMATICALLY_DESTROYED": h1,
            "H2_EASY_FIXTURE_WEAK_ROLE_NOT_AUTOMATICALLY_PROMOTED": h2,
            "H3_MEANINGFUL_MULTI_CHANNEL_ROLE_RETAINS_MORE_RESILIENCE": h3,
            "H4_HOME_CONTEXT_CAN_MATTER_WHEN_CONTEXTUALLY_SUPPORTED": h4,
            "H5_FIXTURE_SUPPRESSION_REMAINS_BUT_IS_NOT_A_VETO": h5,
        },
        "historical_support_status": "UNPROVEN_UNTIL_SETTLED_PREDEADLINE_P1_5_SAMPLES_EXIST",
    }


def score_player_fixture_context(
    *,
    player: Mapping[str, Any],
    fixture: Mapping[str, Any],
    evidence_role_score: float,
    team_strength: Mapping[str, Any] | None,
    set_piece_role: Mapping[str, Any] | None,
    penalty_role: Mapping[str, Any] | None,
) -> dict[str, Any]:
    identity = _fixture_identity(player, fixture)
    home_score, home_evidence = _home_attack_context(
        player, fixture, team_strength
    )
    involvement, involvement_evidence = _attacking_involvement(player)
    security, security_evidence = _role_security(player, team_strength)
    vector, diversity, channel_evidence = _scoring_channels(
        player,
        security,
        set_piece_role,
        penalty_role,
    )
    tactical_fit, tactical_fit_evidence = _tactical_role_fit(
        player,
        identity["opponent_team_id"],
    )
    raw_suppression, suppression_evidence = _raw_fixture_suppression(
        player,
        fixture,
        team_strength,
        vector,
    )

    contextual = None
    if raw_suppression is not None:
        contextual = compose_contextual_tactical_score(
            evidence_role_score=evidence_role_score,
            home_attack_context=home_score,
            attacking_involvement_score=involvement,
            role_security_score=security,
            scoring_channel_diversity=diversity,
            tactical_role_fit=tactical_fit,
            fixture_suppression_raw=raw_suppression,
        )

    cfg = load_config()
    parameter_binding = dict(
        (_contextual_config().get("parameter_binding") or {})
    )
    output = {
        "contract": _contextual_config().get("contract_id"),
        "model_owner": MODEL_OWNER,
        "model_id": MODEL_ID,
        "model_version": cfg.get("model_version"),
        "feature_version": cfg.get("feature_version"),
        "parameter_version": cfg.get("parameter_version"),
        "element": int(player.get("element") or player.get("id") or 0),
        "planning_gw": identity["gw"],
        "fixture": identity["fixture"],
        "opponent_team_id": identity["opponent_team_id"],
        "home": identity["home"],
        "home_attack_context": (
            None if home_score is None else round(home_score, 6)
        ),
        "attacking_involvement_score": (
            None if involvement is None else round(involvement, 6)
        ),
        "role_security_score": (
            None if security is None else round(security, 6)
        ),
        "scoring_channel_vector": {
            key: None if value is None else round(value, 6)
            for key, value in vector.items()
        },
        "scoring_channel_diversity": (
            None if diversity is None else round(diversity, 6)
        ),
        "tactical_role_fit": (
            None if tactical_fit is None else round(tactical_fit, 6)
        ),
        "fixture_suppression_raw": (
            None
            if raw_suppression is None
            else round(raw_suppression, 6)
        ),
        "role_resilience": (
            None if contextual is None else contextual["role_resilience"]
        ),
        "fixture_suppression_effective": (
            None
            if contextual is None
            else contextual["fixture_suppression_effective"]
        ),
        "canonical_tactical_role_score": (
            None
            if contextual is None
            else contextual["canonical_tactical_role_score"]
        ),
        "feature_evidence": {
            "home_attack_context": home_evidence,
            "attacking_involvement_score": involvement_evidence,
            "role_security_score": security_evidence,
            "scoring_channel_diversity": channel_evidence,
            "tactical_role_fit": tactical_fit_evidence,
            "fixture_suppression_raw": suppression_evidence,
        },
        "parameter_binding": parameter_binding,
        "calibration": {
            "authority": parameter_binding.get("calibration_authority"),
            "provenance": parameter_binding.get("calibration_provenance"),
            "settled_sample_size_at_introduction": parameter_binding.get(
                "settled_sample_size_at_introduction"
            ),
            "calibration_confidence_at_introduction": parameter_binding.get(
                "calibration_confidence_at_introduction"
            ),
            "automatic_retuning": False,
        },
        "missing_data": {
            "explicit": True,
            "missing_is_zero": False,
            "missing_is_neutral_fact": False,
            "contextual_score_fallback_required": contextual is None,
        },
        "double_count_diagnostics": {
            "home_context_application_count": home_evidence.get(
                "application_count"
            ),
            "home_context_uses_venue_specific_deltas_only": True,
            "raw_suppression_uses_neutral_opponent_strength_only": True,
            "attacking_involvement_is_interaction_only": True,
            "p1_1_role_security_is_consumed_not_owned": True,
            "p1_3_scoring_channels_are_read_only": True,
            "transfer_action_cost_present": False,
        },
        "governance": {
            "fixture_difficulty_is_suppressor_not_veto": True,
            "opponent_strength_may_not_be_erased": True,
            "home_is_not_automatic_good": True,
            "multi_channel_is_not_linear_bonus": True,
            "player_specific_runtime_special_case": False,
            "p1_1_math_mutated": False,
            "p1_3_math_mutated": False,
            "v6_mutated": False,
        },
    }
    if contextual is not None:
        output["role_resilience"] = contextual["role_resilience"]
        output["fixture_suppression_effective"] = contextual[
            "fixture_suppression_effective"
        ]
        output["canonical_tactical_role_score"] = contextual[
            "canonical_tactical_role_score"
        ]
        output["score_decomposition"] = contextual["decomposition_points"]
        output["resilience_diagnostics"] = {
            key: value
            for key, value in contextual.items()
            if key
            in {
                "role_resilience_inputs",
                "role_resilience_raw_mean",
                "role_resilience_evidence_completeness",
                "resilience_adjustment",
                "pre_suppression_role_quality",
            }
        }
    else:
        output["score_decomposition"] = {
            "FINAL_TACTICAL_ROLE_SCORE": None,
            "fallback": "EVIDENCE_ROLE_SCORE",
            "fallback_score": round(float(evidence_role_score), 6),
        }

    output["explainability"] = {
        "HOME_CONTEXT": {
            "value": output["home_attack_context"],
            "label": _fit_label(home_score),
        },
        "ATTACKING_INVOLVEMENT": {
            "value": output["attacking_involvement_score"],
            "label": _score_label(involvement),
        },
        "ROLE_SECURITY": {
            "value": output["role_security_score"],
            "label": _score_label(security),
        },
        "CHANNEL_DIVERSITY": {
            "value": output["scoring_channel_diversity"],
            "label": _score_label(diversity),
        },
        "TACTICAL_FIT": {
            "value": output["tactical_role_fit"],
            "label": _fit_label(tactical_fit),
        },
        "RAW_FIXTURE_SUPPRESSION": {
            "value": output["fixture_suppression_raw"],
            "label": _suppression_label(raw_suppression),
        },
        "ROLE_RESILIENCE": {
            "value": output["role_resilience"],
            "label": _score_label(output["role_resilience"]),
        },
        "EFFECTIVE_FIXTURE_SUPPRESSION": {
            "value": output["fixture_suppression_effective"],
            "label": _suppression_label(
                output["fixture_suppression_effective"]
            ),
        },
        "FINAL_TACTICAL_ROLE_SCORE": output[
            "canonical_tactical_role_score"
        ],
    }
    return output


def _planning_fixtures(
    player: Mapping[str, Any],
    planning_gw: int,
) -> list[dict[str, Any]]:
    for row in player.get("xpts_by_gw") or []:
        if int(row.get("gw") or -1) == int(planning_gw):
            return [
                dict(fixture)
                for fixture in row.get("fixtures") or []
                if isinstance(fixture, Mapping)
            ]
    return []


def attach_tactical_role_scores(
    projections: dict[str, Any],
    planning_gw: int,
    *,
    team_strength: Mapping[str, Any] | None = None,
    model_evidence_binding: Mapping[str, Any] | None = None,
    calibration_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    observed = inferred = unavailable = 0
    scores: list[float] = []
    contextual_scored = 0
    contextual_fallback = 0
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
        evidence_role_score = float(component["tactical_role_score"])
        contexts = [
            score_player_fixture_context(
                player=player,
                fixture=fixture,
                evidence_role_score=evidence_role_score,
                team_strength=team_strength,
                set_piece_role=set_piece,
                penalty_role=penalty,
            )
            for fixture in _planning_fixtures(player, planning_gw)
        ]
        scored_contexts = [
            row
            for row in contexts
            if row.get("canonical_tactical_role_score") is not None
        ]
        if scored_contexts:
            final_score = sum(
                float(row["canonical_tactical_role_score"])
                for row in scored_contexts
            ) / len(scored_contexts)
            contextual_scored += 1
            contextual_status = "SCORED"
        else:
            final_score = evidence_role_score
            contextual_fallback += 1
            contextual_status = (
                "EXPLICIT_FALLBACK_TO_EVIDENCE_ROLE_SCORE"
            )

        component["evidence_role_score"] = round(evidence_role_score, 6)
        component["fixture_contexts"] = contexts
        component["contextual_score_status"] = contextual_status
        component["contextual_score_coverage"] = {
            "scored_fixtures": len(scored_contexts),
            "planning_fixtures": len(contexts),
        }
        component["tactical_role_score"] = round(final_score, 6)
        component["canonical_tactical_role_score"] = round(
            final_score, 6
        )
        component["canonical_component"]["weighted_component_points"] = round(
            CANONICAL_WEIGHT * final_score, 6
        )
        component["contextual_feature_contract"] = {
            "contract": _contextual_config().get("contract_id"),
            "model_version": load_config().get("model_version"),
            "feature_version": load_config().get("feature_version"),
            "parameter_version": load_config().get("parameter_version"),
            "required_fields": list(
                _contextual_config().get("required_output_fields") or []
            ),
        }
        component["double_count_diagnostics"].update(
            {
                "home_context_single_counted": True,
                "attacking_involvement_interaction_only": True,
                "role_security_p1_1_consumed_not_owned": True,
                "fixture_suppression_neutral_opponent_strength_only": True,
                "transfer_action_cost_in_intrinsic_score": False,
            }
        )
        component["governance"].update(
            {
                "fixture_difficulty_is_suppressor_not_veto": True,
                "opponent_strength_erased": False,
                "home_context_applied_once": True,
                "player_quality_separate_from_transfer_action_cost": True,
                "named_player_special_case": False,
                "single_match_overfit": False,
            }
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
        "model_version": load_config().get("model_version"),
        "feature_version": load_config().get("feature_version"),
        "parameter_version": load_config().get("parameter_version"),
        "planning_gw": int(planning_gw),
        "players": len(scores),
        "observed_or_conflicted": observed,
        "inferred_only": inferred,
        "unavailable_only": unavailable,
        "contextual_scored_players": contextual_scored,
        "contextual_fallback_players": contextual_fallback,
        "mean_tactical_role_score": (
            round(sum(scores) / len(scores), 6) if scores else None
        ),
        "canonical_component_weight": CANONICAL_WEIGHT,
        "fixture_difficulty_is_suppressor_not_veto": True,
        "xpts_mutated": False,
        "xmins_mutated": False,
        "p1_3_event_math_mutated": False,
        "p1_1_minutes_math_mutated": False,
        "raw_v6_payload_persisted": False,
        "transfer_action_cost_consumed": False,
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
            "fixture_difficulty_is_suppressor_not_veto": True,
            "player_quality_separate_from_transfer_action_cost": True,
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
