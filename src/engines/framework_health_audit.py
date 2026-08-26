from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from src.engines.team_value import sell_cost
from src.engines.v4_wc_optimizer import MAX_PER_CLUB, POSITION_COUNTS
from src.utils import CONFIG, DATA, atomic_json, parse_dt, read_json, utcnow

ROOT = Path(__file__).resolve().parents[2]
PRE_OUT = DATA / "framework_health_preflight_v4.json"
OUT = DATA / "framework_health_v4.json"

REGISTRIES = {
    "dss_core": CONFIG / "dss_core_registry.json",
    "dss_extensions": CONFIG / "dss_extension_registry.json",
    "enhancements": CONFIG / "enhancement_layers_registry.json",
    "gate0": CONFIG / "gate0_registry.json",
}
EXPECTED_COUNTS = {"dss_core": 50, "dss_extensions": 16, "enhancements": 8, "gate0": 16}
POSTFLIGHT_OUTPUTS = {
    "data/compliance_audit.json",
    "data/wc_decision_v4.json",
    "data/wc_package_audit_v4.json",
    "data/lineup_decision_v4.json",
    "data/recommendation_sanity_v4.json",
    "data/decision_pipeline_v4.json",
    "data/framework_health_v4.json",
}
LEGAL_FORMS = {"3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-2-3", "5-3-2", "5-4-1"}


def _exists(rel: str) -> bool:
    return (ROOT / rel).exists()


def _rows(name: str, obj: dict) -> list[dict]:
    key = "modules" if name in {"dss_core", "dss_extensions"} else "layers" if name == "enhancements" else "checks"
    return list(obj.get(key) or [])


def _registry_integrity(name: str, obj: dict) -> dict:
    rows = _rows(name, obj)
    ids = [str(x.get("id") or "") for x in rows]
    duplicates = sorted(key for key, value in Counter(ids).items() if key and value > 1)
    expected = EXPECTED_COUNTS[name]
    return {
        "expected": expected,
        "declared": len(rows),
        "duplicate_ids": duplicates,
        "integrity_ok": len(rows) == expected and len(ids) == len(set(ids)) and all(ids),
    }


def _predictions() -> list[dict]:
    return list(read_json(DATA / "predictions_v4.json", {}).get("players") or [])


def _probe_universe() -> tuple[bool, dict]:
    players = list(read_json(DATA / "universe.json", {}).get("players") or [])
    ids = [p.get("element") for p in players]
    valid = [
        p for p in players
        if p.get("element") is not None
        and p.get("name")
        and p.get("position") in POSITION_COUNTS
        and int(p.get("team_id") or 0) > 0
        and int(p.get("now_cost") or 0) > 0
    ]
    ok = bool(players) and len(valid) == len(players) and len(ids) == len(set(ids))
    return ok, {"players": len(players), "valid": len(valid), "unique_ids": len(set(ids))}


def _probe_availability() -> tuple[bool, dict]:
    players = list(read_json(DATA / "universe.json", {}).get("players") or [])
    covered = sum(p.get("status") is not None for p in players)
    ratio = covered / max(1, len(players))
    return bool(players) and ratio >= .95, {"players": len(players), "coverage": round(ratio, 4)}


def _probe_xmins() -> tuple[bool, dict]:
    checked = 0
    for player in _predictions()[:50]:
        for fixture in (player.get("fixtures") or [])[:3]:
            xmins = fixture.get("xmins") or {}
            total = sum(float(xmins.get(key, 0)) for key in ("start_probability", "bench_probability", "dnp_probability"))
            if abs(total - 1) >= .002 or not 0 <= float(xmins.get("expected_minutes", -1)) <= 90:
                return False, {"reason": "invalid xMins distribution", "element": player.get("element")}
            checked += 1
    return checked > 0, {
        "fixture_distributions_checked": checked,
        "quality_note": "functional probe only; richer priors remain V4.7 debt",
    }


def _probe_prediction_component(component: str) -> tuple[bool, dict]:
    fixtures = [fixture for player in _predictions()[:50] for fixture in (player.get("fixtures") or [])[:3]]
    covered = sum(component in (fixture.get("components") or {}) for fixture in fixtures)
    return bool(fixtures) and covered == len(fixtures), {"component": component, "fixtures": len(fixtures), "covered": covered}


def _probe_horizon(key: str) -> tuple[bool, dict]:
    players = _predictions()
    covered = sum(player.get(key) is not None for player in players)
    return bool(players) and covered == len(players), {"field": key, "players": len(players), "covered": covered}


def _json_nonempty(path: Path) -> bool:
    return bool(read_json(path, {}))


def _probe_advanced_sync() -> tuple[bool, dict]:
    files = {
        "shots": _json_nonempty(DATA / "stats" / "shots_gw1.json"),
        "playermatchstats": _json_nonempty(DATA / "stats" / "playermatchstats_gw1.json"),
    }
    return all(files.values()), files


def _probe_advanced_integration() -> tuple[bool, dict]:
    sources = {
        str((fixture.get("provenance") or {}).get("advanced_source"))
        for player in _predictions()[:50]
        for fixture in (player.get("fixtures") or [])[:1]
    }
    integrated = any(source not in {"None", "official_fpl_current_state", "official_fpl"} for source in sources)
    return integrated, {"prediction_sources": sorted(sources), "synced_but_not_consumed": not integrated}


def _probe_defcon() -> tuple[bool, dict]:
    from src.engines.fpl_rules_2026 import DEFCON

    rules_ok = (
        DEFCON["GK"]["eligible"] is False
        and DEFCON["DEF"]["threshold"] == 10
        and DEFCON["MID"]["threshold"] == 12
        and DEFCON["FWD"]["threshold"] == 12
    )
    component_ok, detail = _probe_prediction_component("defcon")
    return rules_ok and component_ok, {"rules_ok": rules_ok, **detail}


def _probe_point_in_time() -> tuple[bool, dict]:
    obj = read_json(DATA / "predictions_v4.json", {})
    players = list(obj.get("players") or [])
    proven = sum(
        bool((fixture.get("provenance") or {}).get("point_in_time"))
        for player in players[:50]
        for fixture in (player.get("fixtures") or [])[:1]
    )
    return obj.get("point_in_time") is True and bool(players) and proven > 0, {"players": len(players), "provenance_samples": proven}


def _probe_uncertainty() -> tuple[bool, dict]:
    fixtures = [fixture for player in _predictions()[:50] for fixture in (player.get("fixtures") or [])[:3]]
    good = sum(
        fixture.get("lower80") is not None
        and fixture.get("upper80") is not None
        and fixture["lower80"] <= fixture.get("xpts", 0) <= fixture["upper80"]
        for fixture in fixtures
    )
    return bool(fixtures) and good == len(fixtures), {"fixtures": len(fixtures), "valid_intervals": good}


def _probe_source_health() -> tuple[bool, dict]:
    health = read_json(DATA / "health.json", {})
    critical = ["bootstrap", "fixtures", "entry", "history", "transfers"]
    states = {key: (health.get(key) or {}).get("status") for key in critical}
    return all(states.get(key) == "LIVE" for key in critical), {"critical_endpoints": states}


def _probe_freshness(max_age_minutes: int = 90) -> tuple[bool, dict]:
    generated = parse_dt(read_json(DATA / "latest.json", {}).get("generated_at"))
    if not generated:
        return False, {"reason": "latest.generated_at missing"}
    age = max(0.0, (utcnow() - generated).total_seconds() / 60)
    return age <= max_age_minutes, {"age_minutes": round(age, 1), "max_age_minutes": max_age_minutes}


def _probe_price() -> tuple[bool, dict]:
    prices = read_json(DATA / "prices.json", {})
    buy = list(prices.get("top_buy_pressure") or [])
    sell = list(prices.get("top_sell_pressure") or [])
    return bool(buy) and bool(sell), {"buy_pressure_rows": len(buy), "sell_pressure_rows": len(sell)}


def _affordability() -> tuple[bool, dict]:
    locked = read_json(CONFIG / "locked_squad.json", {})
    universe = read_json(DATA / "universe.json", {})
    by_id = {int(p["element"]): p for p in universe.get("players", []) if p.get("element") is not None}
    ledger = []
    for row in locked.get("players", []):
        element = int(row.get("element") or -1)
        current = by_id.get(element)
        purchase = row.get("purchase_cost")
        explicit = row.get("selling_price", row.get("sell_cost"))
        if not current or (purchase is None and explicit is None):
            return False, {"reason": "missing owned price evidence", "element": element}
        now = int(current.get("now_cost") or 0)
        selling = int(explicit) if explicit is not None else sell_cost(now, int(purchase))
        if selling <= 0 or selling > now:
            return False, {"reason": "invalid sell cost", "element": element, "sell": selling, "now": now}
        ledger.append({"element": element, "purchase": purchase, "now": now, "sell": selling})
    bank = int(locked.get("itb_tenths") or 0)
    sell_value = sum(item["sell"] for item in ledger)
    return len(ledger) == 15, {
        "owned_players": len(ledger),
        "market_value_tenths": sum(item["now"] for item in ledger),
        "sell_value_tenths": sell_value,
        "bank_tenths": bank,
        "available_budget_tenths": sell_value + bank,
        "formula_reconciled": True,
    }


def _probe_affordability_output() -> tuple[bool, dict]:
    ok, detail = _affordability()
    wc = read_json(DATA / "wc_decision_v4.json", {})
    package = read_json(DATA / "wc_package_audit_v4.json", {})
    expected = detail.get("available_budget_tenths")
    outputs = {
        "wc_budget": wc.get("budget_tenths"),
        "wc_basis": (wc.get("affordability") or {}).get("price_basis"),
        "package_budget": (package.get("guardrails") or {}).get("budget_tenths"),
        "package_basis": (package.get("affordability") or {}).get("price_basis"),
    }
    output_ok = (
        expected is not None
        and outputs["wc_budget"] == expected == outputs["package_budget"]
        and outputs["wc_basis"] == "owned_sell_cost_unowned_now_cost"
        and outputs["package_basis"] == "owned_sell_cost_unowned_now_cost"
    )
    return ok and output_ok, {**detail, **outputs}


def _probe_guardrails(file_name: str, required: list[str]) -> tuple[bool, dict]:
    obj = read_json(DATA / file_name, {})
    guardrails = obj.get("guardrails") or obj.get("performance_guardrails") or {}
    states = {key: guardrails.get(key) for key in required}
    return bool(obj) and all(states.values()), {"file": file_name, "guardrails": states}


def _probe_structural() -> tuple[bool, dict]:
    wc = read_json(DATA / "wc_decision_v4.json", {})
    ids = list(wc.get("optimized_elements") or [])
    hard = wc.get("hard_constraints") or {}
    return len(ids) == 15 and hard.get("legal_xi") is True, {"optimized_players": len(ids), "hard_constraints": hard}


def _probe_direct_challengers() -> tuple[bool, dict]:
    wc = read_json(DATA / "wc_decision_v4.json", {})
    challengers = list(wc.get("direct_challengers") or [])
    valid = sum(
        row.get("owned") is not None
        and row.get("challenger") is not None
        and row.get("position") in POSITION_COUNTS
        for row in challengers
    )
    return bool(challengers) and valid == len(challengers), {"challengers": len(challengers), "valid": valid}


def _probe_lineup() -> tuple[bool, dict]:
    lineup = read_json(DATA / "lineup_decision_v4.json", {})
    xi = list(lineup.get("starting_xi") or [])
    guardrails = lineup.get("guardrails") or {}
    return len(xi) == 11 and lineup.get("formation") in LEGAL_FORMS and all(guardrails.values()), {"xi": len(xi), "formation": lineup.get("formation")}


def _probe_chip() -> tuple[bool, dict]:
    compliance = read_json(DATA / "compliance_audit.json", {})
    return compliance.get("overall") == "PASS", {"compliance": compliance.get("overall")}


def _probe_runtime() -> tuple[bool, dict]:
    timings = read_json(DATA / "decision_pipeline_v4.json", {}).get("timings") or {}
    return float(timings.get("total_pipeline_ms") or 0) > 0, {"timings": timings}


def _probe_learning_loop() -> tuple[str, dict]:
    reconciled = DATA / "validation" / "reconciled"
    samples = list(reconciled.glob("gw*.json")) if reconciled.exists() else []
    if not samples:
        return "PARTIAL", {"reason": "validation framework exists; no reconciled post-GW sample yet", "samples": 0}
    return "ACTIVE", {"reconciled_samples": len(samples)}


def _bool_probe(fn: Callable[[], tuple[bool, dict]], false_status: str = "FAILED") -> tuple[str, dict]:
    ok, detail = fn()
    return ("ACTIVE" if ok else false_status), detail


def _operational_probe(name: str | None, phase: str) -> tuple[str, dict]:
    if not name:
        return "PARTIAL", {"reason": "no operational probe declared"}

    postflight = {
        "sell_cost_affordability": lambda: _bool_probe(_probe_affordability_output),
        "structural_fit": lambda: _bool_probe(_probe_structural),
        "direct_challenger": lambda: _bool_probe(_probe_direct_challengers),
        "bench_utility": lambda: _bool_probe(_probe_lineup),
        "captaincy": lambda: _bool_probe(_probe_lineup),
        "chip_context": lambda: _bool_probe(_probe_chip),
        "decision_recheck": lambda: _bool_probe(_probe_lineup),
        "small_sample_guard": lambda: _bool_probe(lambda: _probe_guardrails("recommendation_sanity_v4.json", ["rate_spike_detection"])),
        "reliability_overlay": lambda: _bool_probe(lambda: _probe_guardrails("recommendation_sanity_v4.json", ["point_in_time_required"])),
        "governed_optimizer": lambda: _bool_probe(lambda: _probe_guardrails("recommendation_sanity_v4.json", ["outgoing_baseline_resistance"])),
        "team_cluster_penalty": lambda: _bool_probe(lambda: _probe_guardrails("recommendation_sanity_v4.json", ["team_cluster_penalty"])),
        "early_season_change_cap": lambda: _bool_probe(lambda: _probe_guardrails("recommendation_sanity_v4.json", ["early_season_multi_change_cap"])),
        "package_churn_penalty": lambda: _bool_probe(lambda: _probe_guardrails("wc_package_audit_v4.json", ["risk_penalty_enabled"])),
        "lineup_robustness": lambda: _bool_probe(_probe_lineup),
        "captain_dnp_guard": lambda: _bool_probe(_probe_lineup),
        "runtime_observability": lambda: _bool_probe(_probe_runtime),
        "uncertainty_robustness": lambda: _bool_probe(_probe_lineup),
        "package_structural": lambda: _bool_probe(_probe_structural),
        "lineup_governance": lambda: _bool_probe(_probe_lineup),
        "final_governance": lambda: _bool_probe(lambda: _probe_guardrails("recommendation_sanity_v4.json", ["raw_optimizer_not_authoritative"])),
    }
    if name in postflight:
        if phase == "preflight":
            return "DEFERRED", {"reason": "requires postflight decision evidence"}
        return postflight[name]()

    active = {
        "universe_identity": _probe_universe,
        "universe_price_position": _probe_universe,
        "universe_registration": _probe_universe,
        "availability": _probe_availability,
        "xmins": _probe_xmins,
        "xmins_distribution": _probe_xmins,
        "advanced_stats_sync": _probe_advanced_sync,
        "defcon_rules": _probe_defcon,
        "clean_sheet_probability": lambda: _probe_prediction_component("clean_sheet"),
        "horizon_3": lambda: _probe_horizon("xpts_3"),
        "horizon_5": lambda: _probe_horizon("xpts_5"),
        "horizon_10": lambda: _probe_horizon("xpts_10"),
        "horizon_15": lambda: _probe_horizon("xpts_15"),
        "leakage_guard": _probe_point_in_time,
        "projection_uncertainty": _probe_uncertainty,
        "manual_authority": lambda: (bool(read_json(CONFIG / "manual_lineup.json", {})), {"file": "config/manual_lineup.json"}),
        "data_freshness": _probe_freshness,
        "source_health": _probe_source_health,
        "price_intelligence": _probe_price,
        "transfer_momentum": _probe_price,
        "current_form": _probe_advanced_sync,
        "multi_horizon": lambda: _probe_horizon("xpts_15"),
    }
    if name in active:
        return _bool_probe(active[name])
    if name == "advanced_stats_integration":
        return _bool_probe(_probe_advanced_integration, false_status="PARTIAL")
    if name == "data_reliability_triangulation":
        source_ok, source_detail = _probe_source_health()
        advanced_ok, advanced_detail = _probe_advanced_integration()
        return (
            "ACTIVE" if source_ok and advanced_ok else "PARTIAL",
            {"source_health": source_detail, "advanced_integration": advanced_detail},
        )
    if name == "learning_loop":
        return _probe_learning_loop()

    known_partial = {
        "tactical_role", "system_fit", "rotation_competition", "set_piece_role", "penalty_role",
        "sustainability", "bonus_route", "team_defensive_risk", "team_attacking_strength",
        "team_defensive_strength", "fixture_context", "opponent_defence_dynamic", "fixture_swing",
        "european_congestion", "domestic_cup_congestion", "international_load", "rest_days",
        "preseason_prior", "last_season_integration", "historical_prior", "regression_risk",
        "price_value", "ownership_context", "calibration_store",
    }
    if name in known_partial:
        return "PARTIAL", {"reason": "capability is incomplete or lacks production decision-output evidence"}
    return "PARTIAL", {"reason": f"unknown operational probe: {name}"}


def _audit_registry(name: str, obj: dict, phase: str) -> dict:
    integrity = _registry_integrity(name, obj)
    audited = []
    counts = Counter()
    for row in _rows(name, obj):
        required = list(row.get("required_files") or [])
        missing = [path for path in required if not _exists(path)]
        deferred = [path for path in missing if phase == "preflight" and path in POSTFLIGHT_OUTPUTS]
        blocking = [path for path in missing if path not in deferred]
        if blocking:
            status = "FAILED" if row.get("critical") else "PARTIAL"
            detail = {"reason": "required evidence missing", "missing_files": blocking}
        elif deferred:
            status = "DEFERRED"
            detail = {"reason": "requires postflight evidence", "deferred_files": deferred}
        else:
            status, detail = _operational_probe(row.get("operational_probe"), phase)
            if status == "FAILED" and not row.get("critical"):
                status = "PARTIAL"
        counts[status] += 1
        audited.append({
            "id": row.get("id"),
            "name": row.get("name"),
            "critical": bool(row.get("critical")),
            "status": status,
            "required_files": required,
            "probe": row.get("operational_probe"),
            "detail": detail,
        })
    return {**integrity, "registry": obj.get("registry"), "counts": dict(counts), "items": audited}


def _gate0(phase: str, compliance: dict, lineup: dict, packages: dict) -> dict:
    locked = read_json(CONFIG / "locked_squad.json", {})
    universe = read_json(DATA / "universe.json", {})
    players = list(locked.get("players") or [])
    by_id = {int(p["element"]): p for p in universe.get("players", []) if p.get("element") is not None}
    checks: dict[str, tuple[str, str]] = {}

    positions = Counter(p.get("position") for p in players)
    checks["G0-01"] = ("PASS" if len(players) == 15 else "FAIL", f"count={len(players)}")
    checks["G0-02"] = ("PASS" if positions.get("GK") == 2 else "FAIL", f"GK={positions.get('GK', 0)}")
    checks["G0-03"] = ("PASS" if positions.get("DEF") == 5 else "FAIL", f"DEF={positions.get('DEF', 0)}")
    checks["G0-04"] = ("PASS" if positions.get("MID") == 5 else "FAIL", f"MID={positions.get('MID', 0)}")
    checks["G0-05"] = ("PASS" if positions.get("FWD") == 3 else "FAIL", f"FWD={positions.get('FWD', 0)}")

    affordability_ok, affordability = _affordability()
    checks["G0-06"] = ("PASS" if affordability_ok and affordability.get("bank_tenths", -1) >= 0 else "FAIL", json.dumps(affordability, sort_keys=True))

    clubs = Counter()
    eligible = True
    identity_ok = True
    for row in players:
        current = by_id.get(int(row.get("element") or -1))
        if not current:
            eligible = False
            identity_ok = False
            continue
        clubs[int(current.get("team_id") or 0)] += 1
        if current.get("status") in {"u", "s"}:
            eligible = False
        if row.get("expected_team") and current.get("team") != row.get("expected_team"):
            identity_ok = False
        if row.get("position") and current.get("position") != row.get("position"):
            identity_ok = False
    checks["G0-07"] = ("PASS" if max(clubs.values(), default=0) <= MAX_PER_CLUB else "FAIL", f"max_club={max(clubs.values(), default=0)}")
    ids = [int(player.get("element") or -1) for player in players]
    checks["G0-08"] = ("PASS" if len(ids) == len(set(ids)) else "FAIL", "element uniqueness")
    checks["G0-09"] = ("PASS" if eligible and identity_ok else "FAIL", f"eligible={eligible},identity_ok={identity_ok}")

    if phase == "postflight" and lineup:
        xi = list(lineup.get("starting_xi") or [])
        xi_ids = {int(player.get("element")) for player in xi if player.get("element") is not None}
        captain = int((lineup.get("captain") or {}).get("element") or -1)
        vice = int((lineup.get("vice_captain") or {}).get("element") or -1)
        bench = lineup.get("bench") or {}
        checks["G0-10"] = ("PASS" if len(xi) == 11 and lineup.get("formation") in LEGAL_FORMS else "FAIL", f"formation={lineup.get('formation')},xi={len(xi)}")
        checks["G0-11"] = ("PASS" if sum(player.get("position") == "GK" for player in xi) == 1 else "FAIL", "starting GK")
        checks["G0-12"] = ("PASS" if captain in xi_ids and vice in xi_ids and captain != vice else "FAIL", f"captain={captain},vice={vice}")
        checks["G0-13"] = ("PASS" if bool(bench.get("gk")) and len(bench.get("order") or []) == 3 else "FAIL", "bench structure")
        chip_ok = (lineup.get("chip_context") or {}).get("single_chip_rule_respected") is True
        checks["G0-14"] = ("PASS" if chip_ok and compliance.get("overall") == "PASS" else "FAIL", f"single_chip={chip_ok},rules={compliance.get('overall')}")
    else:
        for check_id in ("G0-10", "G0-11", "G0-12", "G0-13", "G0-14"):
            checks[check_id] = ("DEFERRED", "requires governed postflight lineup/chip output")

    totals = read_json(DATA / "team.json", {}).get("totals") or {}
    team_sell = totals.get("sell_value")
    formula_matches_team = team_sell is None or int(team_sell) == int(affordability.get("sell_value_tenths") or -1)
    checks["G0-15"] = (
        "PASS" if affordability_ok and formula_matches_team else "FAIL",
        f"formula_reconciled={affordability_ok},team_sell={team_sell},reconstructed_sell={affordability.get('sell_value_tenths')}",
    )

    if phase == "postflight" and packages:
        expected = affordability.get("available_budget_tenths")
        legal = all(
            int(row.get("target_cost") or int(expected or 0) + 1) <= int(expected or 0)
            for rows in (packages.get("packages") or {}).values()
            for row in (rows or [])
        )
        package_budget = (packages.get("guardrails") or {}).get("budget_tenths")
        basis = (packages.get("affordability") or {}).get("price_basis")
        checks["G0-16"] = (
            "PASS" if legal and package_budget == expected and basis == "owned_sell_cost_unowned_now_cost" else "FAIL",
            f"legal={legal},budget={package_budget},expected={expected},basis={basis}",
        )
    else:
        checks["G0-16"] = ("DEFERRED", "requires postflight package audit output")

    registry = read_json(REGISTRIES["gate0"], {})
    names = {item.get("id"): item.get("name") for item in registry.get("checks", [])}
    items = [{"id": key, "name": names.get(key), "status": status, "detail": detail} for key, (status, detail) in sorted(checks.items())]
    result_counts = Counter(item["status"] for item in items)
    return {"phase": phase, "counts": dict(result_counts), "items": items, "pass": result_counts.get("FAIL", 0) == 0}


def audit(phase: str = "postflight", strict: bool = False) -> dict[str, Any]:
    started = time.perf_counter()
    registries = {name: read_json(path, {}) for name, path in REGISTRIES.items()}
    health = {name: _audit_registry(name, registries[name], phase) for name in ("dss_core", "dss_extensions", "enhancements")}
    gate_integrity = _registry_integrity("gate0", registries["gate0"])
    integrity_ok = gate_integrity["integrity_ok"] and all(group["integrity_ok"] for group in health.values())

    compliance = read_json(DATA / "compliance_audit.json", {}) if phase == "postflight" else {}
    lineup = read_json(DATA / "lineup_decision_v4.json", {}) if phase == "postflight" else {}
    packages = read_json(DATA / "wc_package_audit_v4.json", {}) if phase == "postflight" else {}
    gate0 = _gate0(phase, compliance, lineup, packages)

    critical_failed = []
    critical_partial = []
    for group in health.values():
        for item in group["items"]:
            if item["critical"] and item["status"] == "FAILED":
                critical_failed.append(item["id"])
            elif item["critical"] and item["status"] == "PARTIAL":
                critical_partial.append(item["id"])

    source_ok, source_detail = _probe_source_health()
    freshness_ok, freshness_detail = _probe_freshness()
    rules_status = "DEFERRED"
    rules_detail = {"reason": "compliance runs after preflight"}
    if phase == "postflight":
        rules_ok, rules_detail = _probe_chip()
        rules_status = "PASS" if rules_ok else "FAIL"
    else:
        rules_ok = True

    if not integrity_ok or not gate0["pass"] or critical_failed or not source_ok or not rules_ok:
        overall = "RED"
    elif critical_partial or not freshness_ok or any(group["counts"].get("PARTIAL", 0) for group in health.values()):
        overall = "AMBER"
    else:
        overall = "GREEN"

    recommendation_allowed = overall != "RED" and gate0["pass"]
    go_allowed = overall == "GREEN" and gate0["pass"] and (phase == "preflight" or gate0["counts"].get("DEFERRED", 0) == 0)
    out = {
        "schema_version": 464,
        "engine": "v4.6.4-framework-health-operational-probes",
        "phase": phase,
        "overall": overall,
        "decision_engine": "HEALTHY" if overall == "GREEN" else "DEGRADED" if overall == "AMBER" else "BLOCKED",
        "recommendation_allowed": recommendation_allowed,
        "go_allowed": go_allowed,
        "registry_integrity": integrity_ok,
        "gate0": {**gate0, "registry_integrity": gate_integrity},
        "dss_core": health["dss_core"],
        "dss_extensions": health["dss_extensions"],
        "enhancements": health["enhancements"],
        "rules_compliance": {"status": rules_status, "detail": rules_detail},
        "data_freshness": {"status": "PASS" if freshness_ok else "PARTIAL", "detail": freshness_detail},
        "source_health": {"status": "PASS" if source_ok else "FAIL", "detail": source_detail},
        "critical_failed": critical_failed,
        "critical_partial": critical_partial,
        "governance": {
            "gate0_fail_blocks_go": True,
            "critical_framework_fail_blocks_recommendation": True,
            "critical_partial_blocks_unqualified_go": True,
            "file_exists_is_not_sufficient_for_active": True,
            "health_check_must_precede_recommendation": True,
            "raw_optimizer_is_not_final_decision": True,
            "preflight_defers_postflight_outputs": True,
        },
        "performance_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    atomic_json(PRE_OUT if phase == "preflight" else OUT, out)
    print(json.dumps({
        "framework_health": overall,
        "phase": phase,
        "gate0": gate0["counts"],
        "dss_core": health["dss_core"]["counts"],
        "extensions": health["dss_extensions"]["counts"],
        "enhancements": health["enhancements"]["counts"],
        "recommendation_allowed": recommendation_allowed,
        "go_allowed": go_allowed,
        "performance_ms": out["performance_ms"],
    }, ensure_ascii=False))
    if strict and overall == "RED":
        raise SystemExit(2)
    return out


def run() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["preflight", "postflight"], default="postflight")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    return audit(args.phase, strict=args.strict)


if __name__ == "__main__":
    run()
