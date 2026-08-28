from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache
from typing import Any

from src.rules import ELEMENT_TYPE_TO_POSITION
from src.utils import ROOT, read_json

CONFIG_PATH = ROOT / "config" / "intelligence" / "tactical_role_context.json"


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    payload = read_json(CONFIG_PATH, {}) or {}
    if payload.get("contract") != "TACTICAL_ROLE_CONTEXT_V1":
        raise RuntimeError("unexpected tactical role context contract")
    return payload


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _i(value: Any, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _ge(value: Any, threshold: Any) -> bool:
    return value is not None and _f(value) >= _f(threshold)


def classify_role(position: str, advanced: dict[str, Any], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    sample_quality = str(advanced.get("sample_quality") or "NO_ADVANCED_EVIDENCE")
    confidence = str((cfg.get("confidence") or {}).get(sample_quality) or "NONE")
    minutes = max(0.0, _f(advanced.get("minutes")))
    metrics = {
        "xg_per90": advanced.get("xg_per90"),
        "xa_per90": advanced.get("xa_per90"),
        "touches_opposition_box_per90": advanced.get("touches_opposition_box_per90"),
        "chances_created_per90": advanced.get("chances_created_per90"),
        "shots_per90": advanced.get("shots_per90"),
    }
    if minutes <= 0 or sample_quality == "NO_ADVANCED_EVIDENCE":
        return {
            "model": cfg.get("model_id"),
            "profile": "UNASSESSED",
            "confidence": "NONE",
            "sample_quality": sample_quality,
            "evidence_minutes": round(minutes, 1),
            "metrics": metrics,
            "decision_influence": "ADVISORY_ONLY",
            "reason": "no advanced role evidence",
        }

    thresholds = (cfg.get("role_thresholds") or {}).get(position) or {}
    profile = "BASE_PROFILE"
    reason = "observed attacking involvement below role thresholds"

    if position == "GK":
        profile = "GOALKEEPER_PROFILE"
        reason = "Official FPL goalkeeper classification"
    elif position == "DEF":
        attacking = _ge(metrics["touches_opposition_box_per90"], thresholds.get("attacking_box_touches_per90")) or _ge(metrics["chances_created_per90"], thresholds.get("attacking_chances_created_per90"))
        threat = _ge(metrics["xg_per90"], thresholds.get("box_threat_xg_per90")) or _ge(metrics["shots_per90"], thresholds.get("box_threat_shots_per90"))
        if attacking:
            profile = "ATTACKING_DEFENDER_PROFILE"
            reason = "elevated box-touch or chance-creation involvement"
        elif threat:
            profile = "BOX_THREAT_DEFENDER_PROFILE"
            reason = "elevated shooting or xG involvement"
        else:
            profile = "DEFENSIVE_BASE_PROFILE"
    elif position == "MID":
        shooter = _ge(metrics["touches_opposition_box_per90"], thresholds.get("shooter_box_touches_per90")) or _ge(metrics["shots_per90"], thresholds.get("shooter_shots_per90")) or _ge(metrics["xg_per90"], thresholds.get("shooter_xg_per90"))
        creator = _ge(metrics["chances_created_per90"], thresholds.get("creator_chances_created_per90")) or _ge(metrics["xa_per90"], thresholds.get("creator_xa_per90"))
        if shooter and creator:
            profile = "HYBRID_ATTACKING_MID_PROFILE"
            reason = "both shooting/box and chance-creation thresholds met"
        elif shooter:
            profile = "ADVANCED_RUNNER_SHOOTER_PROFILE"
            reason = "shooting or box-involvement threshold met"
        elif creator:
            profile = "CREATOR_PROFILE"
            reason = "chance-creation or xA threshold met"
        else:
            profile = "DEEP_OR_LOW_ATTACKING_MID_PROFILE"
    elif position == "FWD":
        shooter = _ge(metrics["touches_opposition_box_per90"], thresholds.get("shooter_box_touches_per90")) or _ge(metrics["shots_per90"], thresholds.get("shooter_shots_per90")) or _ge(metrics["xg_per90"], thresholds.get("shooter_xg_per90"))
        creator = _ge(metrics["chances_created_per90"], thresholds.get("creator_chances_created_per90")) or _ge(metrics["xa_per90"], thresholds.get("creator_xa_per90"))
        if shooter and creator:
            profile = "COMPLETE_FORWARD_PROFILE"
            reason = "both focal-shooter and creator thresholds met"
        elif shooter:
            profile = "FOCAL_SHOOTER_PROFILE"
            reason = "shooting or box-involvement threshold met"
        elif creator:
            profile = "CREATOR_FORWARD_PROFILE"
            reason = "chance-creation or xA threshold met"
        else:
            profile = "LOW_ATTACKING_EVIDENCE_FORWARD_PROFILE"

    return {
        "model": cfg.get("model_id"),
        "profile": profile,
        "confidence": confidence,
        "sample_quality": sample_quality,
        "evidence_minutes": round(minutes, 1),
        "metrics": metrics,
        "decision_influence": "ADVISORY_ONLY",
        "reason": reason,
    }


def build_team_system_context(elements: list[dict[str, Any]], match_rows: list[dict[str, Any]], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    shape_cfg = cfg.get("team_shape") or {}
    identity: dict[int, tuple[int, str]] = {}
    for player in elements:
        element = _i(player.get("id"), -1)
        team_id = _i(player.get("team"), -1)
        position = str(ELEMENT_TYPE_TO_POSITION.get(_i(player.get("element_type"))) or "UNKNOWN")
        if element > 0 and team_id > 0:
            identity[element] = (team_id, position)

    starters: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
    for row in match_rows:
        player_id = _i(row.get("player_id"), -1)
        mapped = identity.get(player_id)
        if not mapped:
            continue
        if _f(row.get("minutes_played")) <= 0 or _i(row.get("start_min"), -1) != 0:
            continue
        match_id = str(row.get("match_id") or "").strip()
        if not match_id:
            continue
        team_id, position = mapped
        starters[(match_id, team_id)][position] += 1

    team_shapes: dict[int, list[dict[str, Any]]] = defaultdict(list)
    required_total = int(shape_cfg.get("valid_starter_count") or 11)
    required_gk = int(shape_cfg.get("required_goalkeepers") or 1)
    for (match_id, team_id), counts in starters.items():
        starter_total = sum(counts.values())
        valid = starter_total == required_total and counts.get("GK", 0) == required_gk
        shape = None
        if valid:
            shape = f"{counts.get('DEF', 0)}-{counts.get('MID', 0)}-{counts.get('FWD', 0)}"
        team_shapes[team_id].append({
            "match_id": match_id,
            "starter_count": starter_total,
            "position_counts": {key: int(counts.get(key, 0)) for key in ("GK", "DEF", "MID", "FWD")},
            "fpl_position_shape": shape,
            "valid": valid,
        })

    out: dict[str, Any] = {}
    for team_id, matches in team_shapes.items():
        valid_shapes = [row["fpl_position_shape"] for row in matches if row.get("valid") and row.get("fpl_position_shape")]
        count = len(valid_shapes)
        dominant = None
        consistency = 0.0
        if valid_shapes:
            dominant, dominant_count = Counter(valid_shapes).most_common(1)[0]
            consistency = dominant_count / len(valid_shapes)
        if count >= int(shape_cfg.get("minimum_matches_high") or 4) and consistency >= _f(shape_cfg.get("high_consistency"), 0.75):
            confidence = "HIGH"
        elif count >= int(shape_cfg.get("minimum_matches_medium") or 2):
            confidence = "MEDIUM"
        elif count == 1:
            confidence = "LOW"
        else:
            confidence = "NONE"
        out[str(team_id)] = {
            "model": cfg.get("model_id"),
            "label": "FPL_POSITION_SHAPE",
            "dominant_shape": dominant,
            "shape_consistency": round(consistency, 4),
            "valid_matches": count,
            "observed_matches": len(matches),
            "confidence": confidence,
            "decision_influence": "ADVISORY_ONLY",
            "matches": matches,
            "governance": {
                "not_claimed_as_true_tactical_formation": True,
                "advanced_stats_are_enrichment": True,
            },
        }
    return out
