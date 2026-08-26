from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_package_governance_registry.json"


def _cfg() -> dict[str, Any]:
    data = load_json_config(CONFIG)
    policy = data.get("policy")
    if not isinstance(policy, dict):
        raise RuntimeError("invalid V5 package governance registry")
    return data


def govern_packages(packages: dict[str, Any], truth: dict[str, Any]) -> dict[str, Any]:
    policy = _cfg()["policy"]
    if packages.get("status") != "READY":
        return {
            "status": "BLOCKED",
            "reason": "package optimizer is not READY",
            "selected_package": None,
            "selected_package_id": None,
            "manual_authority_override": False,
        }

    ranked = [row for row in packages.get("packages") or [] if isinstance(row, dict)]
    hold = packages.get("hold") if isinstance(packages.get("hold"), dict) else None
    if hold is None:
        hold = next((row for row in ranked if row.get("id") == "HOLD"), None)
    if hold is None:
        raise RuntimeError("package governance requires HOLD package from optimizer")

    context = truth.get("context") if isinstance(truth.get("context"), dict) else {}
    team = truth.get("team") if isinstance(truth.get("team"), dict) else {}
    phase = str(context.get("phase") or "")
    team_authority = str(team.get("authority") or "")
    authoritative_phases = {str(value) for value in policy.get("authoritative_phases") or []}
    authoritative_team_authorities = {
        str(value) for value in policy.get("authoritative_team_authorities") or []
    }
    freeze = bool(policy.get("freeze_locked_composition_when_authoritative")) and (
        phase in authoritative_phases and team_authority in authoritative_team_authorities
    )

    optimizer_best = ranked[0] if ranked else hold
    best_challenger = next((row for row in ranked if row.get("id") != "HOLD"), None)
    auto_select = bool(policy.get("auto_select_optimizer_candidate", False))
    selected = hold if freeze or not auto_select else optimizer_best

    if freeze and bool(policy.get("require_hold_package_when_frozen", True)) and selected.get("id") != "HOLD":
        raise RuntimeError("authoritative manual LOCK must resolve to HOLD package")

    selected_score = selected.get("score") if isinstance(selected.get("score"), dict) else {}
    selected_legal = bool(selected.get("legal")) and bool(selected_score.get("valid"))
    if not selected_legal:
        return {
            "status": "BLOCKED",
            "reason": "selected package failed local legality/score validity",
            "selected_package": selected,
            "selected_package_id": selected.get("id"),
            "manual_authority_override": freeze,
        }

    return {
        "status": "READY",
        "model": _cfg().get("model_id"),
        "selected_package": selected,
        "selected_package_id": selected.get("id"),
        "optimizer_best_candidate": optimizer_best,
        "optimizer_best_candidate_id": optimizer_best.get("id"),
        "optimizer_best_challenger": best_challenger if policy.get("expose_optimizer_best_challenger", True) else None,
        "optimizer_best_challenger_id": best_challenger.get("id") if best_challenger else None,
        "manual_authority_override": freeze,
        "team_authority": team_authority,
        "phase": phase,
        "governance": {
            "optimizer_is_candidate_generator_only": bool(policy.get("optimizer_is_candidate_generator_only", True)),
            "auto_select_optimizer_candidate": auto_select,
            "locked_composition_frozen": freeze,
            "manual_authority_overrides_optimizer_candidate": bool(
                policy.get("manual_authority_overrides_optimizer_candidate", True)
            ),
        },
    }
