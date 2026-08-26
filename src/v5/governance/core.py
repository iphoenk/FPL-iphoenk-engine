from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config

CORE = "config/dss_core_registry.json"
EXT = "config/dss_extension_registry.json"
ENH = "config/enhancement_layers_registry.json"
GATE = "config/gate0_registry.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _registry(path: str, key: str) -> list[dict[str, Any]]:
    data = load_json_config(path)
    rows = data.get(key)
    if not isinstance(rows, list):
        raise RuntimeError(f"invalid framework registry {path}")
    return rows


def _integrity(rows: list[dict[str, Any]], expected: int) -> dict[str, Any]:
    ids = [str(x.get("id")) for x in rows]
    duplicates = sorted(k for k, v in Counter(ids).items() if v > 1)
    return {"expected": expected, "declared": len(rows), "duplicate_ids": duplicates, "integrity_ok": len(rows) == expected and not duplicates}


def gate0_preflight(truth: dict[str, Any]) -> dict[str, Any]:
    rules = truth.get("rules") or {}
    squad_rules = rules.get("squad") or {}
    team = truth.get("team") or {}
    squad = team.get("squad") or []
    validation = team.get("validation") or {}
    finance = team.get("finance") or {}
    expected_counts = {str(k): int(v) for k, v in (squad_rules.get("position_counts") or {}).items()}
    counts = {pos: sum(str(p.get("position")) == pos for p in squad) for pos in expected_counts}
    clubs = Counter(int(p.get("team_id") or -1) for p in squad)
    purchase_total = sum(int(p.get("purchase_cost") or 0) for p in (finance.get("players") or []))
    bank = int(finance.get("bank") or 0)
    budget = int(squad_rules.get("budget_tenths") or 0)
    ids = [int(p.get("element") or -1) for p in squad]
    checks = {
        "G0-01": (len(squad) == int(squad_rules.get("squad_size") or 0), f"count={len(squad)},expected={squad_rules.get('squad_size')}"),
        "G0-02": (counts.get("GK") == expected_counts.get("GK"), f"GK={counts.get('GK')},expected={expected_counts.get('GK')}"),
        "G0-03": (counts.get("DEF") == expected_counts.get("DEF"), f"DEF={counts.get('DEF')},expected={expected_counts.get('DEF')}"),
        "G0-04": (counts.get("MID") == expected_counts.get("MID"), f"MID={counts.get('MID')},expected={expected_counts.get('MID')}"),
        "G0-05": (counts.get("FWD") == expected_counts.get("FWD"), f"FWD={counts.get('FWD')},expected={expected_counts.get('FWD')}"),
        "G0-06": (purchase_total + bank <= budget, f"purchase_total={purchase_total},itb={bank},budget={budget}"),
        "G0-07": (max(clubs.values(), default=0) <= int(squad_rules.get("max_players_per_club") or 0), f"max_club={max(clubs.values(), default=0)},limit={squad_rules.get('max_players_per_club')}"),
        "G0-08": (len(ids) == len(set(ids)), "element uniqueness"),
        "G0-09": (bool(validation.get("passed")), f"team_validation={validation.get('passed')}"),
        "G0-15": (bool(finance.get("sell_value_complete")), f"sell_value_complete={finance.get('sell_value_complete')},ledger_rows={len(finance.get('players') or [])}"),
    }
    gate_rows = _registry(GATE, "checks")
    items = []
    for row in gate_rows:
        gid = str(row.get("id"))
        if gid in checks:
            passed, detail = checks[gid]
            items.append({"id": gid, "name": row.get("name"), "status": "PASS" if passed else "FAIL", "detail": detail})
        else:
            items.append({"id": gid, "name": row.get("name"), "status": "DEFERRED", "detail": "requires governed lineup/chip/winning-package output"})
    counter = Counter(x["status"] for x in items)
    return {"phase": "preflight", "ruleset_id": rules.get("ruleset_id"), "counts": dict(counter), "items": items, "pass": counter.get("FAIL", 0) == 0, "registry_integrity": _integrity(gate_rows, 16)}


def _probe_state(probe: str, evidence: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    prediction = evidence.get("prediction") or {}
    decision = evidence.get("decision") or {}
    evaluation = evidence.get("evaluation") or {}
    price = evidence.get("price") or {}
    truth = evidence.get("truth") or {}
    players = prediction.get("players") or []
    xmins_ok = bool(players) and all(abs(sum(float((p.get("xmins") or {}).get(k, 0)) for k in ("start_probability", "bench_probability", "dnp_probability")) - 1.0) < 0.003 for p in players)
    horizons_ok = bool(players) and all(all(str(h) in (p.get("horizons") or {}) for h in (3, 5, 10, 15)) for p in players)
    strength = prediction.get("team_strength") or {}
    strength_ok = len(strength.get("teams") or []) == 20 and bool(strength.get("matchups"))
    optimizer_ok = decision.get("status") == "READY" and bool(decision.get("gate0_prevalidated"))
    eval_ok = isinstance(evaluation.get("accuracy"), dict) and isinstance(evaluation.get("ledger"), dict)
    challenger_ok = isinstance(evaluation.get("challenger_scorecard"), dict)
    price_ok = isinstance(price, dict) and isinstance(price.get("prices"), dict)
    team_ok = bool((truth.get("team") or {}).get("validation", {}).get("passed"))
    active = {
        "xmins": xmins_ok, "xmins_distribution": xmins_ok, "projection_uncertainty": xmins_ok, "small_sample_guard": xmins_ok,
        "team_attacking_strength": strength_ok, "team_defensive_strength": strength_ok, "opponent_defence_dynamic": strength_ok,
        "clean_sheet_probability": strength_ok, "fixture_context": strength_ok, "fixture_swing": strength_ok,
        "horizon_3": horizons_ok, "horizon_5": horizons_ok, "horizon_10": horizons_ok, "horizon_15": horizons_ok,
        "budget_opportunity_cost": optimizer_ok, "direct_challenger": optimizer_ok, "governed_optimizer": optimizer_ok,
        "package_churn_penalty": optimizer_ok, "package_structural": optimizer_ok, "multi_horizon": optimizer_ok,
        "calibration_store": eval_ok, "learning_loop": eval_ok and int(((evaluation.get("accuracy") or {}).get("overall") or {}).get("sample_size") or 0) > 0,
        "challenger_scorecard": challenger_ok, "price_intelligence": price_ok,
        "structural_fit": team_ok, "manual_authority": bool((truth.get("team") or {}).get("authority")),
        "decision_recheck": optimizer_ok and team_ok,
    }
    if active.get(probe):
        return "ACTIVE", {"microservice_probe": True, "probe": probe}
    if probe == "learning_loop" and eval_ok:
        return "PARTIAL", {"microservice_probe": True, "reason": "awaiting settled prediction sample"}
    if probe == "challenger_scorecard" and challenger_ok:
        return "PARTIAL", {"microservice_probe": True, "reason": "external observations may be absent"}
    return "PARTIAL", {"reason": "capability not yet backed by a passing microservice-native operational probe"}


def _audit_registry(path: str, key: str, expected: int, evidence: dict[str, Any]) -> dict[str, Any]:
    rows = _registry(path, key)
    items = []
    for row in rows:
        probe = str(row.get("operational_probe") or row.get("probe") or "")
        status, detail = _probe_state(probe, evidence)
        items.append({"id": row.get("id"), "name": row.get("name"), "critical": bool(row.get("critical")), "status": status, "probe": probe, "detail": detail})
    counts = Counter(x["status"] for x in items)
    return {**_integrity(rows, expected), "counts": dict(counts), "items": items}


def build_health(truth: dict[str, Any], prediction: dict[str, Any], price: dict[str, Any], decision: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
    evidence = {"truth": truth, "prediction": prediction, "price": price, "decision": decision, "evaluation": evaluation}
    gate = gate0_preflight(truth)
    core = _audit_registry(CORE, "modules", 50, evidence)
    ext = _audit_registry(EXT, "modules", 16, evidence)
    enh = _audit_registry(ENH, "layers", 8, evidence)
    integrity = gate["registry_integrity"]["integrity_ok"] and core["integrity_ok"] and ext["integrity_ok"] and enh["integrity_ok"]
    critical_failed = [x for group in (core, ext, enh) for x in group["items"] if x["critical"] and x["status"] == "FAILED"]
    critical_partial = [x for group in (core, ext, enh) for x in group["items"] if x["critical"] and x["status"] == "PARTIAL"]
    recommendation_allowed = bool(gate["pass"] and integrity and not critical_failed)
    postflight_complete = all(x["status"] == "PASS" for x in gate["items"])
    go_allowed = recommendation_allowed and postflight_complete and not critical_partial
    overall = "RED" if not recommendation_allowed else ("GREEN" if go_allowed else "AMBER")
    return {
        "framework_schema": 5, "generated_at": _now(), "auditor": "v5-microservice-governance-v1", "overall": overall,
        "decision_engine": "HEALTHY" if go_allowed else ("DEGRADED" if recommendation_allowed else "BLOCKED"),
        "recommendation_allowed": recommendation_allowed, "go_allowed": go_allowed, "registry_integrity": integrity,
        "rules_registry": {"status": "PASS" if truth.get("rules") else "FAIL", "detail": {"ruleset_id": (truth.get("rules") or {}).get("ruleset_id"), "authority": (truth.get("rules") or {}).get("authority")}},
        "gate0": gate, "dss_core": core, "dss_extensions": ext, "enhancements": enh,
        "critical_failed": critical_failed, "critical_partial": critical_partial,
        "governance": {"gate0_fail_blocks_go": True, "preflight_deferred_blocks_unqualified_go": True, "dss_core_count_immutable": 50, "enhancement_count_immutable": 8, "service_boundary_enforced": True},
    }
