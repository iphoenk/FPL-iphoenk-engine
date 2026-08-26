from __future__ import annotations

import hashlib
import json
from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_reporting_registry.json"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _state(decision: dict[str, Any], price: dict[str, Any], governance: dict[str, Any]) -> dict[str, Any]:
    lineup = decision.get("lineup") or {}
    xi = sorted(int(x.get("element")) for x in lineup.get("starting_xi") or [] if x.get("element") is not None)
    alerts = ((price.get("alerts") or {}).get("alerts") or []) if isinstance(price.get("alerts"), dict) else (price.get("alerts") or [])
    price_state = sorted((int(x.get("element") or -1), str(x.get("risk_direction") or ""), str(x.get("urgency") or "")) for x in alerts if x.get("owned") and str(x.get("urgency") or "").upper() in {"HIGH", "CRITICAL"})
    return {
        "squad": decision.get("selected_package_id"),
        "starting_xi": xi,
        "formation": lineup.get("formation"),
        "captain": (lineup.get("captain") or {}).get("element"),
        "vice_captain": (lineup.get("vice_captain") or {}).get("element"),
        "chip": (lineup.get("chip_context") or {}).get("active_chip"),
        "price": price_state,
        "critical_health": {"overall": governance.get("overall"), "go_allowed": governance.get("go_allowed")},
    }


def _changes(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    old = previous.get("state") if isinstance(previous.get("state"), dict) else {}
    if not old:
        return {"initial_report": True, "material_change": True, "changed": ["initial_baseline"]}
    changed = [key for key, value in current.items() if old.get(key) != value]
    return {"initial_report": False, "material_change": bool(changed), "changed": changed}


def _captaincy(lineup: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_config(CONFIG).get("captaincy") or {}
    safe = lineup.get("captain_safe_pool") or []
    captain = lineup.get("captain") or {}
    vice = lineup.get("vice_captain") or {}
    if not captain:
        return {"decision": "OPEN", "confidence": "LOW", "reason": "captain candidate unavailable"}
    margin = _f(safe[0].get("captain_score")) - _f(safe[1].get("captain_score")) if len(safe) > 1 else 0.0
    start_p = _f(captain.get("start_probability"), _f(captain.get("xmins_start_probability")))
    mins = _f(captain.get("expected_minutes"), _f(captain.get("xmins")))
    dnp = _f(captain.get("dnp_probability"), max(0.0, 1.0 - start_p))
    checks = {
        "start_probability": start_p >= _f(cfg.get("minimum_start_probability_for_lock"), 0.85),
        "expected_minutes": mins >= _f(cfg.get("minimum_expected_minutes_for_lock"), 70.0),
        "dnp_risk": dnp <= _f(cfg.get("maximum_dnp_probability_for_lock"), 0.10),
        "ranking_margin": margin >= _f(cfg.get("minimum_score_margin_for_lock"), 0.40),
    }
    passed = sum(bool(x) for x in checks.values())
    decision = "LOCK" if all(checks.values()) else ("LEAN" if passed >= 3 else "OPEN")
    return {"decision": decision, "confidence": "HIGH" if decision == "LOCK" else ("MEDIUM" if decision == "LEAN" else "LOW"), "captain": captain, "vice_captain": vice, "candidate_margin": round(margin, 4), "checks": checks}


def _lineup(lineup: dict[str, Any], compact: bool) -> dict[str, Any]:
    cfg = load_json_config(CONFIG).get("starting_xi") or {}
    battle = lineup.get("main_starting_xi_battle") or {}
    margin = _f(battle.get("margin"))
    decision = "LOCK" if battle.get("status") == "CLEAR" and margin >= _f(cfg.get("lock_margin"), 0.75) else "OPEN"
    return {"decision": decision, "formation": lineup.get("formation"), "battle": battle, "starting_xi": [] if compact else lineup.get("starting_xi") or [], "bench": [] if compact else lineup.get("bench") or []}


def _price(price: dict[str, Any], watchlist: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_config(CONFIG).get("price_radar") or {}
    allowed = {str(x) for x in cfg.get("allowed_urgencies") or ["HIGH", "CRITICAL"]}
    alerts = ((price.get("alerts") or {}).get("alerts") or []) if isinstance(price.get("alerts"), dict) else (price.get("alerts") or [])
    rows = [x for x in alerts if str(x.get("urgency") or "").upper() in allowed]
    external_ready = watchlist.get("status") == "READY"
    return {"owned": [x for x in rows if x.get("owned")], "external": [x for x in rows if not x.get("owned")] if external_ready else [], "external_status": "READY" if external_ready else "INSUFFICIENT_EVIDENCE"}


def build_report(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    truth = payload.get("truth") if isinstance(payload.get("truth"), dict) else {}
    prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
    price = payload.get("price") if isinstance(payload.get("price"), dict) else {}
    governance = payload.get("governance") if isinstance(payload.get("governance"), dict) else {}
    previous = payload.get("previous_report_state") if isinstance(payload.get("previous_report_state"), dict) else {}
    if not decision or not truth:
        raise ValueError("reporting requires decision and truth payloads")
    current = _state(decision, price, governance)
    changes = _changes(current, previous)
    compact = bool((cfg.get("stable_report") or {}).get("compact_when_no_material_change", True) and not changes["material_change"])
    lineup = decision.get("lineup") or {}
    watchlist = decision.get("watchlist") or {"status": "INSUFFICIENT_EVIDENCE", "positions": {}}
    selected = decision.get("selected_package") or {}
    trace = decision.get("decision_trace") or {}
    user_report = {
        "layer": "USER_REPORT",
        "report_mode": "COMPACT_DELTA" if compact else "FULL_DECISION",
        "decision": {"state": "HOLD" if decision.get("selected_package_id") == "HOLD" else ("CHANGE" if selected else "REVIEW"), "selected_package_id": decision.get("selected_package_id"), "confidence": trace.get("confidence")},
        "changes_since_last_report": changes,
        "owned_squad": {"authority": (truth.get("team") or {}).get("authority"), "count": len((truth.get("team") or {}).get("team_value_ledger") or [])},
        "starting_xi": _lineup(lineup, compact),
        "captaincy": _captaincy(lineup),
        "chip": lineup.get("chip_context") or {},
        "price_radar": _price(price, watchlist),
        "external_watchlist": watchlist,
        "engine_line": {"status": governance.get("overall") or governance.get("status") or "UNKNOWN", "review_only": not bool(governance.get("go_allowed", False))},
        "action_board": [],
    }
    actions = []
    actions.append({"action": user_report["decision"]["state"], "target": "SQUAD"})
    actions.append({"action": user_report["starting_xi"]["decision"], "target": "XI"})
    actions.append({"action": user_report["captaincy"]["decision"], "target": "CAPTAIN"})
    for pos, rows in (watchlist.get("positions") or {}).items():
        for row in rows[:1]:
            actions.append({"action": "WATCH", "target": row.get("name"), "position": pos})
    user_report["action_board"] = actions[: int((cfg.get("action_board") or {}).get("max_items") or 8)]
    technical = {
        "layer": "TECHNICAL_APPENDIX",
        "decision_trace": trace,
        "dss": decision.get("dss") or {},
        "prediction_quality": prediction.get("prediction_quality") or {},
        "gate0_preflight_pass": decision.get("gate0_preflight_pass"),
        "governance": governance,
        "performance": payload.get("performance") or {},
        "provenance": {"ruleset_id": decision.get("ruleset_id"), "prediction_model": prediction.get("model_version"), "decision_model": decision.get("model")},
    }
    state = {"fingerprint": _fingerprint(current), "state": current}
    return {"schema_version": int(cfg.get("schema_version") or 1), "model": cfg.get("model_id"), "user_report": user_report, "technical_appendix": technical, "report_state": state}
