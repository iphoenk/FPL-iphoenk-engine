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
    v5_rows = v5_lineup.get("starters") or v5_lineup.get("starting_xi") or v5.get("starting_xi") or []
    v3_xi = _ids(v3_rows)
    v5_xi = _ids(v5_rows)
    xi_available = len(v3_xi) == 11 and len(v5_xi) == 11
    xi_diff = len(v3_xi.symmetric_difference(v5_xi)) if xi_available else None

    v3_cap = (v3.get("captain") or {}).get("element") if isinstance(v3.get("captain"), dict) else v3.get("captain")
    v5_cap = (v5_lineup.get("captain") or {}).get("element") if isinstance(v5_lineup.get("captain"), dict) else None
    v3_lock = str(v3.get("captain_state") or "").upper() == "LOCK"
    v5_lock = str(((v5.get("user_report") or {}).get("captaincy") or {}).get("decision") or "").upper() == "LOCK"

    v3_authority = str(v3.get("decision_squad_authority") or v3.get("squad_authority") or "").lower()
    v5_authority = str(v5.get("decision_squad_authority") or v5.get("squad_authority") or "").lower()
    v3_full_squad = _ids(v3.get("decision_squad_rows") or v3.get("squad_rows") or [])
    v5_team = v5.get("team_summary") if isinstance(v5.get("team_summary"), dict) else {}
    v5_owned_ids = {int(x) for x in (v5_team.get("owned_ids") or [])}
    if not v5_owned_ids:
        v5_owned_ids = _ids(v5_team.get("squad") or [])
    full_identity_complete = len(v3_full_squad) == 15 and len(v5_owned_ids) == 15
    full_identity_match = full_identity_complete and v3_full_squad == v5_owned_ids

    explicit_v3_manual = bool(v3.get("manual_lock_authoritative")) or v3_authority in {"user_lock", "manual_lock"}
    legacy_predeadline_label = v3_authority == "pre_deadline_wc"
    legacy_label_materially_equivalent_to_public = (
        legacy_predeadline_label
        and full_identity_match
        and v5_authority == "official_public"
    )
    if explicit_v3_manual:
        manual_authority_parity = v5_authority == "user_lock"
    elif legacy_predeadline_label:
        manual_authority_parity = v5_authority == "user_lock" or legacy_label_materially_equivalent_to_public
    else:
        manual_authority_parity = True

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
        "manual_lock": manual_authority_parity,
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
        "authority_equivalence": {
            "v3_full_squad_count": len(v3_full_squad),
            "v5_owned_count": len(v5_owned_ids),
            "full_identity_complete": full_identity_complete,
            "full_identity_match": full_identity_match,
            "legacy_predeadline_label_materially_equivalent_to_public": legacy_label_materially_equivalent_to_public,
        },
        "required_real_cycles": int(cfg.get("required_cycles_before_production_candidate") or 3),
    }
