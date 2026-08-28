from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.engines.p0_framework_health_overlay import _recount, _set_probe_status
from src.engines.tactical_decision_consumption import apply_lineup_overlay
from src.rules import LINEUP_RULES
from src.utils import DATA, atomic_json, read_json

HEALTH_PATH = DATA / "framework_health.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lineup_probe() -> tuple[bool, dict[str, Any]]:
    lineup = read_json(DATA / "lineup_decision.json", {})
    xi = list(lineup.get("starting_xi") or [])
    xi_ids = {int(x.get("element")) for x in xi if x.get("element") is not None}
    formation = lineup.get("formation")
    captain = int((lineup.get("captain") or {}).get("element") or -1)
    vice = int((lineup.get("vice_captain") or {}).get("element") or -1)
    bench = lineup.get("bench") or {}
    bench_gk = bench.get("gk") or {}
    bench_order = list(bench.get("order") or [])
    safe_pool = list(lineup.get("captain_safe_pool") or [])
    safe_ids = {int(x.get("element")) for x in safe_pool if x.get("element") is not None}
    battle = lineup.get("main_starting_xi_battle") or {}
    required_xi = int(LINEUP_RULES.get("starting_xi_size") or 11)
    required_gk = int(LINEUP_RULES.get("starting_goalkeepers") or 1)
    required_bench_outfield = int((LINEUP_RULES.get("bench") or {}).get("outfield") or 3)
    legal_forms = set(LINEUP_RULES.get("legal_formations") or [])
    ok = (
        len(xi) == required_xi
        and formation in legal_forms
        and sum(1 for x in xi if x.get("position") == "GK") == required_gk
        and captain in xi_ids
        and vice in xi_ids
        and captain != vice
        and bool(bench_gk)
        and len(bench_order) == required_bench_outfield
        and captain in safe_ids
        and vice in safe_ids
        and battle.get("status") in {"CLOSE", "CLEAR", "NO_ALTERNATIVE"}
        and (lineup.get("chip_context") or {}).get("single_chip_rule_respected") is True
    )
    governance = lineup.get("governance") or {}
    return ok, {
        "model": lineup.get("model"),
        "planning_gw": lineup.get("planning_gw"),
        "formation": formation,
        "starting_xi": len(xi),
        "captain": (lineup.get("captain") or {}).get("name"),
        "vice_captain": (lineup.get("vice_captain") or {}).get("name"),
        "safe_pool": len(safe_pool),
        "battle_status": battle.get("status"),
        "battle_margin": battle.get("margin"),
        "tactical_xi_tiebreak_applied": bool(governance.get("tactical_xi_tiebreak_applied")),
        "tactical_captain_tiebreak_applied": bool(governance.get("tactical_captain_tiebreak_applied")),
        "tactical_vice_tiebreak_applied": bool(governance.get("tactical_vice_tiebreak_applied")),
        "tactical_direct_xpts_mutation": bool(governance.get("tactical_direct_xpts_mutation")),
        "single_chip_rule_respected": (lineup.get("chip_context") or {}).get("single_chip_rule_respected"),
    }


def _package_decision_probe() -> tuple[bool, dict[str, Any]]:
    package = read_json(DATA / "package_decision.json", {})
    selected = package.get("selected_package") or {}
    governance = package.get("governance") or {}
    manual = package.get("manual_authority_override") is True
    selected_hold_when_manual = (not manual) or selected.get("id") == "HOLD"
    ok = (
        bool(selected)
        and selected.get("legal") is True
        and (selected.get("score") or {}).get("valid") is True
        and package.get("current_squad_legal") is True
        and package.get("gate0_revalidated") is True
        and governance.get("optimizer_is_candidate_generator_only") is True
        and selected_hold_when_manual
    )
    return ok, {
        "model": package.get("model"),
        "planning_gw": package.get("planning_gw"),
        "selected_package_id": package.get("selected_package_id"),
        "optimizer_best_candidate_id": package.get("optimizer_best_candidate_id"),
        "manual_authority_override": manual,
        "gate0_revalidated": package.get("gate0_revalidated"),
    }


def run() -> dict[str, Any]:
    # Tactical evidence is consumed here, after the canonical lineup model has
    # produced legal candidates and before the final lineup health probe. The
    # overlay can only resolve configured close calls; it never changes xPts.
    tactical_lineup = apply_lineup_overlay()
    health = read_json(HEALTH_PATH, {})
    if not health:
        raise RuntimeError("framework_health.json missing before lineup governance overlay")
    lineup_ok, lineup_detail = _lineup_probe()
    package_ok, package_detail = _package_decision_probe()
    _set_probe_status(
        health,
        {"lineup_robustness", "captain_dnp_guard", "lineup_governance"},
        "ACTIVE" if lineup_ok else "FAILED",
        {"lineup_governance_operational_probe": True, **lineup_detail},
    )
    _set_probe_status(
        health,
        {"final_governance"},
        "ACTIVE" if lineup_ok and package_ok else "FAILED",
        {"lineup_governance_operational_probe": True, **lineup_detail, **package_detail},
    )
    health["lineup_governance"] = {
        "status": "ACTIVE" if lineup_ok else "FAILED",
        "lineup": lineup_detail,
        "package": {"status": "ACTIVE" if package_ok else "FAILED", **package_detail},
    }
    health.setdefault("governance", {}).update({
        "lineup_is_governed_output_not_raw_optimizer": True,
        "captain_and_vice_use_dnp_guard": True,
        "manual_lock_precedes_optimizer_candidate": True,
        "postflight_gate0_consumes_lineup_and_package_decisions": True,
        "tactical_close_call_consumption_enabled": True,
        "tactical_direct_xpts_mutation": False,
        "tactical_consumption_contract": "TACTICAL_DECISION_CONSUMPTION_V1",
    })
    health["tactical_lineup_consumption"] = {
        "xi_tiebreak_applied": bool((tactical_lineup.get("governance") or {}).get("tactical_xi_tiebreak_applied")),
        "captain_tiebreak_applied": bool((tactical_lineup.get("governance") or {}).get("tactical_captain_tiebreak_applied")),
        "vice_tiebreak_applied": bool((tactical_lineup.get("governance") or {}).get("tactical_vice_tiebreak_applied")),
        "xpts_mutated": False,
    }
    health["lineup_overlay_generated_at"] = _now()
    _recount(health)
    atomic_json(HEALTH_PATH, health)
    print(json.dumps({
        "overall": health.get("overall"),
        "phase": health.get("phase"),
        "gate0": (health.get("gate0") or {}).get("counts"),
        "lineup": health["lineup_governance"]["status"],
        "package": health["lineup_governance"]["package"]["status"],
        "tactical": health.get("tactical_lineup_consumption"),
        "extensions": (health.get("dss_extensions") or {}).get("counts"),
        "enhancements": (health.get("enhancements") or {}).get("counts"),
        "go_allowed": health.get("go_allowed"),
    }, ensure_ascii=False))
    return health


if __name__ == "__main__":
    run()
