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


def govern_checkpoint(
    latest: dict,
    health: dict,
    sanity: dict,
    lineup: dict,
    locked: dict,
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
    context = dict(latest.get("checkpoint_context") or {})
    freshness = _freshness(latest, evaluated_at)
    gate0_pass = (health.get("gate0") or {}).get("pass") is True
    framework_red = health.get("overall") == "RED"
    health_go = health.get("go_allowed") is True
    simulation = context.get("is_simulation") is True
    post_final = context.get("post_final_emergency_only") is True
    wildcard_active = bool(locked.get("wildcard_active"))
    expected_authority = "LOCKED_PRE_DEADLINE" if wildcard_active else "OFFICIAL_SUBMITTED"
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

    return {
        "schema_version": 491,
        "engine": "v4.9.1-checkpoint-governance",
        "evaluated_at": evaluated_at.isoformat(),
        "checkpoint_context": context,
        "action_state": action,
        "headline": action_definition.get("headline"),
        "summary": action_definition.get("summary"),
        "structure_action": action_definition.get("structure_action"),
        "squad": {
            "authority": latest.get("squad_authority"),
            "authority_ok": authority_ok,
            "wildcard_active": wildcard_active,
            "locked_players": len(locked.get("players") or []),
            "composition_status": "LOCKED_15" if wildcard_active else "SUBMITTED_OR_CURRENT",
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
        },
    }


def run(now: str | None = None) -> dict:
    out = govern_checkpoint(
        read_json(DATA / "latest.json", {}),
        read_json(DATA / "framework_health_v4.json", {}),
        read_json(DATA / "recommendation_sanity_v4.json", {}),
        read_json(DATA / "lineup_decision_v4.json", {}),
        read_json(CONFIG / "locked_squad.json", {}),
        now=now,
    )
    atomic_json(OUTFILE, out)
    print(json.dumps({
        "checkpoint": (out.get("checkpoint_context") or {}).get("policy_id"),
        "action": out.get("action_state"),
        "headline": out.get("headline"),
        "governed_verdict": (out.get("decision") or {}).get("governed_verdict"),
    }, ensure_ascii=False))
    return out


def cli() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--now", help="Timezone-aware deterministic evaluation time")
    args = parser.parse_args()
    return run(args.now)


if __name__ == "__main__":
    cli()
