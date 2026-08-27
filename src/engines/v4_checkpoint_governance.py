from __future__ import annotations

import argparse
import json
from datetime import datetime

from src.utils import CONFIG, DATA, atomic_json, parse_dt, read_json, utcnow

OUTFILE = DATA / "checkpoint_decision_v4.json"
ACTIONS = CONFIG / "report_action_registry.json"


def _freshness(latest: dict, now: datetime) -> dict:
    context = latest.get("checkpoint_context") or {}
    maximum = int(context.get("max_snapshot_age_minutes") or 90)
    generated = parse_dt(latest.get("generated_at"))
    if not generated:
        return {"pass": False, "age_minutes": None, "max_age_minutes": maximum, "reason": "generated_at_missing"}
    age = max(0.0, (now - generated).total_seconds() / 60.0)
    return {"pass": age <= maximum, "age_minutes": round(age, 2), "max_age_minutes": maximum, "reason": None if age <= maximum else "snapshot_stale"}


def _action_definition(action: str, actions: dict) -> dict:
    row = dict((actions.get("actions") or {}).get(action) or {})
    if not row:
        raise RuntimeError(f"report action missing: {action}")
    return row


def _planning_authority(locked: dict, scorecard: dict) -> dict:
    planning = scorecard.get("planning_gw") or {}
    basis = planning.get("squad_basis") or {}
    if basis.get("effective_authority"):
        expected = str(basis["effective_authority"])
        override_applied = bool(basis.get("override_applied"))
        target_gw = basis.get("override_target_gw")
        source = basis.get("authority_source")
        baseline_gw = basis.get("baseline_gw")
        planning_gw = basis.get("planning_gw")
    else:
        # Backward-compatible fallback for unit callers without a scorecard.
        override_applied = bool(locked.get("wildcard_active"))
        expected = "LOCKED_PRE_DEADLINE" if override_applied else "OFFICIAL_SUBMITTED"
        target_gw = locked.get("target_gw")
        source = locked.get("authority_source") if override_applied else "OFFICIAL_FPL_PICKS"
        baseline_gw = None
        planning_gw = None
    active_chip = str(planning.get("active_chip") or "NONE").upper()
    wildcard_for_planning = active_chip == "WILDCARD" or (override_applied and bool(locked.get("wildcard_active")))
    return {
        "expected_authority": expected,
        "override_applied": override_applied,
        "override_target_gw": target_gw,
        "authority_source": source,
        "baseline_gw": baseline_gw,
        "planning_gw": planning_gw,
        "wildcard_active": wildcard_for_planning,
    }


def govern_checkpoint(
    latest: dict,
    health: dict,
    sanity: dict,
    lineup: dict,
    locked: dict,
    scorecard: dict | None = None,
    now: datetime | str | None = None,
    actions: dict | None = None,
) -> dict:
    if isinstance(now, str):
        evaluated_at = parse_dt(now)
    else:
        evaluated_at = now
    evaluated_at = evaluated_at or utcnow()
    if evaluated_at.tzinfo is None:
        raise RuntimeError("checkpoint governance now must be timezone-aware")

    actions = actions or read_json(ACTIONS, {})
    scorecard = scorecard or {}
    context = dict(latest.get("checkpoint_context") or {})
    freshness = _freshness(latest, evaluated_at)
    gate0_pass = (health.get("gate0") or {}).get("pass") is True
    framework_red = health.get("overall") == "RED"
    health_go = health.get("go_allowed") is True
    simulation = context.get("is_simulation") is True
    post_final = context.get("post_final_emergency_only") is True
    authority = _planning_authority(locked, scorecard)
    wildcard_active = authority["wildcard_active"]
    expected_authority = authority["expected_authority"]
    authority_ok = latest.get("squad_authority") == expected_authority
    verdict = sanity.get("final_verdict") or "KEEP_15"

    reasons: list[str] = []
    if not gate0_pass:
        reasons.append("GATE0_FAILED")
    if framework_red:
        reasons.append("FRAMEWORK_RED")
    if not authority_ok:
        reasons.append("SQUAD_AUTHORITY_MISMATCH")
    if not freshness["pass"]:
        reasons.append("SNAPSHOT_STALE")
    if simulation:
        reasons.append("SIMULATED_AS_OF")
    if health.get("critical_partial"):
        reasons.append("CRITICAL_FRAMEWORK_PARTIAL")
    if health.get("critical_warmup"):
        reasons.append("CRITICAL_PREDICTION_WARMUP")
    if verdict == "OPTIONAL_IMPROVEMENT":
        reasons.append("OPTIONAL_NOT_AUTOMATIC_GO")

    if not gate0_pass or framework_red or not authority_ok:
        action = "BLOCKED"
    elif not freshness["pass"]:
        action = "REFRESH_REQUIRED"
    elif simulation:
        action = "SIMULATION_ONLY"
    elif post_final:
        action = "EMERGENCY_UPDATE_ONLY"
    elif not health_go:
        action = "HOLD"
    elif verdict == "MATERIAL_UPGRADE" and (sanity.get("recommended_package") or {}).get("material_eligible") is True:
        action = "GO"
    elif verdict == "OPTIONAL_IMPROVEMENT":
        action = "REVIEW_REQUIRED"
    else:
        action = "HOLD"

    action_definition = _action_definition(action, actions)
    explicit_lineup_lock = str(lineup.get("status") or "").upper() == "FINAL_LOCKED"
    final_review = context.get("is_final_review") is True
    lineup_state = "FINAL_LOCKED" if explicit_lineup_lock else "FINAL_REVIEW_REQUIRED" if final_review else "ADJUSTABLE"
    recommended = sanity.get("recommended_package") or {}
    critical_partial = list(health.get("critical_partial") or [])
    critical_warmup = list(health.get("critical_warmup") or [])

    return {
        "schema_version": 492,
        "engine": "v4.9.2-checkpoint-governance",
        "evaluated_at": evaluated_at.isoformat(),
        "checkpoint_context": context,
        "action_state": action,
        "headline": action_definition.get("headline"),
        "summary": action_definition.get("summary"),
        "structure_action": action_definition.get("structure_action"),
        "squad": {
            "authority": latest.get("squad_authority"),
            "expected_authority": expected_authority,
            "authority_ok": authority_ok,
            "baseline_gw": authority.get("baseline_gw"),
            "planning_gw": authority.get("planning_gw"),
            "planning_override_applied": authority.get("override_applied"),
            "planning_override_target_gw": authority.get("override_target_gw"),
            "authority_source": authority.get("authority_source"),
            "wildcard_active": wildcard_active,
            "locked_players": len(locked.get("players") or []),
            "composition_status": "LOCKED_15" if expected_authority == "LOCKED_PRE_DEADLINE" else "SUBMITTED_OR_CURRENT",
            "hit_recommendation": "NOT_APPLICABLE_WILDCARD_ACTIVE" if wildcard_active else "UNASSESSED",
        },
        "decision": {
            "raw_package_verdict": sanity.get("raw_package_verdict"),
            "governed_verdict": verdict,
            "recommended_replacements": recommended.get("replacements"),
            "recommended_out": [row.get("name") for row in recommended.get("out", [])],
            "recommended_in": [row.get("name") for row in recommended.get("in", [])],
            "material_eligible": recommended.get("material_eligible"),
            "execution_authorized": action == "GO",
        },
        "lineup": {
            "status": lineup_state,
            "formation": lineup.get("formation"),
            "captain": (lineup.get("captain") or {}).get("name"),
            "vice_captain": (lineup.get("vice_captain") or {}).get("name"),
            "governance": (lineup.get("governance") or {}).get("decision"),
            "requires_explicit_final_lock": not explicit_lineup_lock,
        },
        "personal_gw_scorecard": {
            "status": scorecard.get("status", "UNAVAILABLE"),
            "previous_gw": scorecard.get("previous_gw") or {"status": "UNAVAILABLE"},
            "planning_gw": scorecard.get("planning_gw") or {"status": "UNAVAILABLE"},
            "headline": scorecard.get("headline") or {},
            "history": scorecard.get("history") or [],
        },
        "readiness": {
            "framework_health": health.get("overall"),
            "pipeline_health": health.get("pipeline_health", health.get("overall")),
            "prediction_health": health.get("prediction_health"),
            "decision_engine": health.get("decision_engine"),
            "capability_coverage": health.get("capability_coverage"),
            "gate0_pass": gate0_pass,
            "health_go_allowed": health_go,
            "freshness": freshness,
            "critical_partial": critical_partial,
            "critical_warmup": critical_warmup,
            "reasons": reasons,
        },
        "report_scope": list(context.get("report_scope") or []),
        "guardrails": {
            "raw_optimizer_not_authoritative": True,
            "optional_improvement_is_not_automatic_go": True,
            "simulation_never_authorizes_action": True,
            "freshness_failure_blocks_action": True,
            "locked_15_separate_from_lineup_lock": True,
            "wildcard_active_means_no_hit": True,
            "scorecard_is_reporting_only": True,
            "planning_authority_target_gw_aware": True,
            "stale_wildcard_flag_does_not_force_future_lock": True,
        },
    }


def run(now: str | None = None) -> dict:
    out = govern_checkpoint(
        read_json(DATA / "latest.json", {}),
        read_json(DATA / "framework_health_v4.json", {}),
        read_json(DATA / "recommendation_sanity_v4.json", {}),
        read_json(DATA / "lineup_decision_v4.json", {}),
        read_json(CONFIG / "locked_squad.json", {}),
        scorecard=read_json(DATA / "gw_scorecard_v4.json", {}),
        now=now,
    )
    atomic_json(OUTFILE, out)
    print(json.dumps({
        "checkpoint": (out.get("checkpoint_context") or {}).get("policy_id"),
        "action": out.get("action_state"),
        "headline": out.get("headline"),
        "governed_verdict": (out.get("decision") or {}).get("governed_verdict"),
        "previous_gw": ((out.get("personal_gw_scorecard") or {}).get("headline") or {}).get("previous"),
        "planning_gw": ((out.get("personal_gw_scorecard") or {}).get("headline") or {}).get("planning"),
        "squad_basis": (out.get("squad") or {}).get("authority_source"),
    }, ensure_ascii=False))
    return out


def cli() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--now", help="Timezone-aware deterministic evaluation time")
    args = parser.parse_args()
    return run(args.now)


if __name__ == "__main__":
    cli()
