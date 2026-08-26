from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_shadow_parity_registry.json"


def _ids(rows: Any) -> set[int]:
    return {int(x.get("element")) for x in (rows or []) if isinstance(x, dict) and x.get("element") is not None}


def compare(v3: dict[str, Any], v5: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    tol = cfg.get("tolerances") or {}
    v3_xi = _ids((v3.get("starting_xi") or (v3.get("lineup") or {}).get("starting_xi")))
    v5_xi = _ids(((v5.get("decision_summary") or {}).get("lineup") or {}).get("starting_xi") or (v5.get("starting_xi") or []))
    xi_diff = len(v3_xi.symmetric_difference(v5_xi)) if v3_xi and v5_xi else None
    v3_cap = (v3.get("captain") or {}).get("element") if isinstance(v3.get("captain"), dict) else v3.get("captain")
    v5_lineup = (v5.get("decision_summary") or {}).get("lineup") or v5.get("lineup") or {}
    v5_cap = (v5_lineup.get("captain") or {}).get("element")
    v3_lock = str(v3.get("captain_state") or "").upper() == "LOCK"
    v5_lock = str(((v5.get("user_report") or {}).get("captaincy") or {}).get("decision") or "").upper() == "LOCK"
    checks = {
        "starting_xi": xi_diff is None or xi_diff <= int(tol.get("starting_xi_symmetric_difference_max") or 2),
        "captaincy": not (tol.get("captain_must_match_when_both_lock") and v3_lock and v5_lock) or v3_cap == v5_cap,
        "ruleset": not v3.get("ruleset_id") or not v5.get("ruleset_id") or v3.get("ruleset_id") == v5.get("ruleset_id"),
        "manual_lock": not bool(v3.get("manual_lock_authoritative")) or (v5.get("squad_authority") == "user_lock"),
        "legality": not bool(v3.get("legal") is False) and not bool(((v5.get("framework_health") or {}).get("gate0") or {}).get("pass") is False),
    }
    return {"model": cfg.get("model_id"), "pass": all(checks.values()), "checks": checks, "starting_xi_symmetric_difference": xi_diff, "captain": {"v3": v3_cap, "v5": v5_cap}, "required_real_cycles": int(cfg.get("required_cycles_before_production_candidate") or 3)}
