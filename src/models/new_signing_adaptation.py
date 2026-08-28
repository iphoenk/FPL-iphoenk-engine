from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache
from typing import Any

from src.models.player_identity import norm_name
from src.utils import ROOT

POLICY_PATH = ROOT / "config" / "intelligence" / "new_signing_adaptation.json"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _team_code(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        number = float(text)
        if number.is_integer():
            return str(int(number))
    except (TypeError, ValueError):
        pass
    return text.casefold() or None


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def annotate_prior_team_context(
    prior_payload: dict[str, Any],
    current_elements: list[dict[str, Any]],
    previous_payload: dict[str, Any],
) -> dict[str, Any]:
    """Annotate previous-season priors with current-vs-previous club context.

    Player identity remains the join key. Club identity is used only to decide
    whether old starter/role evidence is portable to the current club.
    """
    rows = list(previous_payload.get("rows") or [])
    by_code = {str(row.get("code")): row for row in rows if row.get("code") not in (None, "")}
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        full = norm_name(f"{row.get('first_name', '')} {row.get('second_name', '')}")
        if full:
            by_name[full].append(row)

    annotated = 0
    changed = 0
    unknown = 0
    prior_players = prior_payload.get("players") or {}
    for player in current_elements:
        element = str(int(player["id"]))
        prior = prior_players.get(element)
        if not prior:
            continue
        row = by_code.get(str(player.get("code")))
        if row is None:
            full = norm_name(f"{player.get('first_name', '')} {player.get('second_name', '')}")
            candidates = by_name.get(full, [])
            row = candidates[0] if len(candidates) == 1 else None
        previous_code = _team_code((row or {}).get("team_code"))
        current_code = _team_code(player.get("team_code"))
        transfer_flag = None if previous_code is None or current_code is None else previous_code != current_code
        prior.update({
            "previous_team_code": previous_code,
            "current_team_code": current_code,
            "team_change_detected": transfer_flag,
            "previous_team_name": (row or {}).get("team") or (row or {}).get("team_name"),
        })
        annotated += 1
        changed += int(transfer_flag is True)
        unknown += int(transfer_flag is None)

    prior_payload["transfer_context_summary"] = {
        "annotated_prior_players": annotated,
        "team_changes_detected": changed,
        "team_context_unknown": unknown,
        "method": "stable_player_identity_then_previous_vs_current_team_code",
    }
    prior_payload.setdefault("governance", {}).update({
        "old_club_role_is_not_assumed_portable": True,
        "team_change_detection_does_not_change_player_identity": True,
    })
    return prior_payload


def classify(historical: dict[str, Any] | None) -> str:
    historical = historical or {}
    if not historical:
        return "NO_PREVIOUS_PL_PRIOR"
    changed = historical.get("team_change_detected")
    if changed is True:
        return "INTRA_PL_TRANSFER"
    if changed is False:
        return "SAME_CLUB"
    return "PRIOR_TEAM_UNKNOWN"


def build_adaptation(
    player: dict[str, Any],
    historical: dict[str, Any] | None,
    team_matches_played: int = 0,
) -> dict[str, Any]:
    historical = historical or {}
    policy = load_policy()
    state = classify(historical)
    cfg = (policy.get("states") or {}).get(state) or {}

    starter_retention = _clamp(_f(cfg.get("starter_prior_retention"), 1.0))
    minutes_retention = _clamp(_f(cfg.get("starter_minutes_retention"), starter_retention))
    attack_retention = _clamp(_f(cfg.get("attacking_prior_retention"), 1.0))
    evidence_retention = _clamp(_f(cfg.get("prior_evidence_retention"), 1.0))

    raw_start = historical.get("start_probability")
    neutral_start = _clamp(_f(policy.get("neutral_start_probability"), 0.62), 0.01, 0.99)
    adapted_start = None
    if raw_start is not None and starter_retention > 0:
        adapted_start = neutral_start + (_clamp(_f(raw_start), 0.01, 0.99) - neutral_start) * starter_retention

    raw_starter_minutes = historical.get("avg_minutes_when_start")
    neutral_minutes = max(45.0, min(90.0, _f(policy.get("neutral_starter_minutes"), 70.0)))
    adapted_starter_minutes = None
    if raw_starter_minutes is not None and minutes_retention > 0:
        adapted_starter_minutes = neutral_minutes + (_f(raw_starter_minutes) - neutral_minutes) * minutes_retention
        adapted_starter_minutes = max(45.0, min(90.0, adapted_starter_minutes))

    retire_after = cfg.get("retire_old_club_starter_prior_after_team_matches")
    old_role_prior_retired = False
    if retire_after is not None and int(team_matches_played or 0) >= int(retire_after):
        adapted_start = None
        adapted_starter_minutes = None
        old_role_prior_retired = state != "SAME_CLUB"

    current_starts = max(0, int(player.get("starts") or 0))
    confidence_ceiling = cfg.get("confidence_ceiling")
    unlock_starts = int(cfg.get("current_starts_to_unlock_confidence") or 0)
    if confidence_ceiling and unlock_starts > 0 and current_starts >= unlock_starts:
        confidence_ceiling = None

    return {
        "contract": policy.get("contract"),
        "model": policy.get("model_id"),
        "state": state,
        "team_change_detected": historical.get("team_change_detected"),
        "previous_team_code": historical.get("previous_team_code"),
        "current_team_code": historical.get("current_team_code") or _team_code(player.get("team_code")),
        "starter_prior_retention": round(starter_retention, 4),
        "starter_minutes_retention": round(minutes_retention, 4),
        "attacking_prior_retention": round(attack_retention, 4),
        "prior_evidence_retention": round(evidence_retention, 4),
        "raw_prior_start_probability": round(_f(raw_start), 4) if raw_start is not None else None,
        "adapted_prior_start_probability": round(adapted_start, 4) if adapted_start is not None else None,
        "raw_starter_minutes_prior": round(_f(raw_starter_minutes), 1) if raw_starter_minutes is not None else None,
        "adapted_starter_minutes_prior": round(adapted_starter_minutes, 1) if adapted_starter_minutes is not None else None,
        "adapted_prior_evidence_minutes": round(max(0.0, _f(historical.get("minutes"))) * evidence_retention, 1),
        "confidence_ceiling": confidence_ceiling,
        "current_starts_to_unlock_confidence": unlock_starts or None,
        "old_role_prior_retired": old_role_prior_retired,
        "team_matches_played": int(team_matches_played or 0),
        "governance": {
            "skill_and_role_priors_separated": True,
            "old_club_starter_security_not_copied_one_for_one": True,
            "current_official_starts_remain_primary_new_club_evidence": True,
            "cross_league_prior_not_fabricated": state == "NO_PREVIOUS_PL_PRIOR",
        },
    }
