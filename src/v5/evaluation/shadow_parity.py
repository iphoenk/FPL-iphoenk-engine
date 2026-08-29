from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_shadow_parity_registry.json"


def _ids(rows: Any) -> set[int]:
    return {
        int(x.get("element"))
        for x in (rows or [])
        if isinstance(x, dict) and x.get("element") is not None
    }


def _v5_lineup(v5: dict[str, Any]) -> dict[str, Any]:
    decision = v5.get("decision_summary") if isinstance(v5.get("decision_summary"), dict) else {}
    lineup = decision.get("lineup") if isinstance(decision.get("lineup"), dict) else {}
    if lineup:
        return lineup
    return v5.get("lineup") if isinstance(v5.get("lineup"), dict) else {}


def compare(v3: dict[str, Any], v5: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    tol = cfg.get("tolerances") or {}

    v3_rows = v3.get("starting_xi") or (v3.get("lineup") or {}).get("starting_xi") or []
    v5_lineup = _v5_lineup(v5)
    # Native V5 calls the XI `starters`; legacy bridges may still expose
    # `starting_xi`. Missing XI evidence is a parity failure, never a pass.
    v5_rows = v5_lineup.get("starters") or v5_lineup.get("starting_xi") or v5.get("starting_xi") or []
    v3_xi = _ids(v3_rows)
    v5_xi = _ids(v5_rows)
    xi_available = len(v3_xi) == 11 and len(v5_xi) == 11
    xi_diff = len(v3_xi.symmetric_difference(v5_xi)) if xi_available else None

    v3_cap = (v3.get("captain") or {}).get("element") if isinstance(v3.get("captain"), dict) else v3.get("captain")
    v5_cap = (v5_lineup.get("captain") or {}).get("element") if isinstance(v5_lineup.get("captain"), dict) else None
    v3_lock = str(v3.get("captain_state") or "").upper() == "LOCK"
    v5_lock = str(((v5.get("user_report") or {}).get("captaincy") or {}).get("decision") or "").upper() == "LOCK"

    # Shadow parity is a DECISION-parity contract. A live production snapshot can
    # legitimately have OFFICIAL_SUBMITTED as scoring authority while its next-GW
    # planning decision still comes from a pre-deadline user lock. Prefer the
    # explicit decision authority when present; falling back to generic squad
    # authority is only for older artifacts that do not expose the distinction.
    v3_authority = str(v3.get("decision_squad_authority") or v3.get("squad_authority") or "").lower()
    v3_manual = bool(v3.get("manual_lock_authoritative")) or v3_authority in {
        "pre_deadline_wc",
        "user_lock",
        "manual_lock",
    }
    v5_authority = str(v5.get("decision_squad_authority") or v5.get("squad_authority") or "").lower()

    v5_gate0 = (v5.get("framework_health") or {}).get("gate0") or {}
    v5_legality_known = v5_gate0.get("pass") is not None
    v5_legal = v5_gate0.get("pass") is True
    v3_legal = v3.get("legal") is not False

    checks = {
        "starting_xi": xi_available and xi_diff <= int(tol.get("starting_xi_symmetric_difference_max") or 2),
        "captaincy": v5_cap is not None and (
            not (tol.get("captain_must_match_when_both_lock") and v3_lock and v5_lock)
            or v3_cap == v5_cap
        ),
        "ruleset": bool(v3.get("ruleset_id")) and bool(v5.get("ruleset_id")) and v3.get("ruleset_id") == v5.get("ruleset_id"),
        "manual_lock": (not v3_manual) or v5_authority == "user_lock",
        "legality": v3_legal and v5_legality_known and v5_legal,
    }
    return {
        "model": cfg.get("model_id"),
        "pass": all(checks.values()),
        "checks": checks,
        "starting_xi_symmetric_difference": xi_diff,
        "starting_xi_evidence_complete": xi_available,
        "captain": {"v3": v3_cap, "v5": v5_cap},
        "authority": {"v3": v3_authority or None, "v5": v5_authority or None},
        "required_real_cycles": int(cfg.get("required_cycles_before_production_candidate") or 3),
    }
