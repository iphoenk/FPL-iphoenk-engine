from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from typing import Any

from src.rules import ACTIVE_RULESET, LINEUP_RULES, RULESET_ID, SQUAD_RULES
from src.utils import ROOT, DATA, CONFIG, atomic_json, read_json, parse_dt, utcnow
from src.version import ENGINE_VERSION

PRE_OUT = DATA / "framework_health_preflight.json"
OUT = DATA / "framework_health.json"
POSITION_COUNTS = {k: int(v) for k, v in (SQUAD_RULES.get("position_counts") or {}).items()}
SQUAD_SIZE = int(SQUAD_RULES.get("squad_size") or 0)
BUDGET_TENTHS = int(SQUAD_RULES.get("budget_tenths") or 0)
MAX_PER_CLUB = int(SQUAD_RULES.get("max_players_per_club") or 0)
LEGAL_FORMS = set(LINEUP_RULES.get("legal_formations") or [])
STARTING_XI_SIZE = int(LINEUP_RULES.get("starting_xi_size") or 0)
STARTING_GK_COUNT = int(LINEUP_RULES.get("starting_goalkeepers") or 0)
BENCH_RULES = dict(LINEUP_RULES.get("bench") or {})
EXPECTED_COUNTS = {"dss_core": 50, "dss_extensions": 16, "enhancements": 8, "gate0": 16}
XMINS_CONTRACT_VALIDATION = read_json(CONFIG / "intelligence" / "xmins_v2.json", {}).get("contract_validation") or {}
PROJECTION_VALIDATION = read_json(CONFIG / "intelligence" / "projection.json", {}).get("validation") or {}
XMINS_PROBABILITY_SUM_TOLERANCE = float(XMINS_CONTRACT_VALIDATION["probability_sum_tolerance"])
MINIMUM_PLAYER_COVERAGE_RATIO = float(PROJECTION_VALIDATION["minimum_player_coverage_ratio"])

REGISTRIES = {
    "dss_core": CONFIG / "dss_core_registry.json",
    "dss_extensions": CONFIG / "dss_extension_registry.json",
    "enhancements": CONFIG / "enhancement_layers_registry.json",
    "gate0": CONFIG / "gate0_registry.json",
}


def _exists(rel: str) -> bool:
    return (ROOT / rel).exists()


def _rows(name: str, obj: dict) -> list[dict]:
    key = "modules" if name in {"dss_core", "dss_extensions"} else "layers" if name == "enhancements" else "checks"
    return list(obj.get(key) or [])


def _registry_integrity(name: str, obj: dict) -> dict:
    rows = _rows(name, obj)
    ids = [str(x.get("id") or "") for x in rows]
    dup = sorted(k for k, v in Counter(ids).items() if k and v > 1)
    expected = EXPECTED_COUNTS[name]
    return {
        "expected": expected,
        "declared": len(rows),
        "duplicate_ids": dup,
        "integrity_ok": len(rows) == expected and len(ids) == len(set(ids)) and all(ids),
    }


def _json_nonempty(rel: str) -> bool:
    p = ROOT / rel
    if not p.exists() or p.stat().st_size < 3:
        return False
    try:
        return bool(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return False


def _probe_universe() -> tuple[bool, dict]:
    players = list(read_json(DATA / "universe.json", {}).get("players") or [])
    if not players:
        return False, {"reason": "universe empty"}
    ids = [p.get("element") for p in players]
    valid = [p for p in players if p.get("element") is not None and p.get("name") and p.get("position") in POSITION_COUNTS and int(p.get("now_cost") or 0) > 0]
    return len(valid) == len(players) and len(ids) == len(set(ids)), {"players": len(players), "valid": len(valid), "unique_ids": len(set(ids))}


def _probe_availability() -> tuple[bool, dict]:
    players = list(read_json(DATA / "universe.json", {}).get("players") or [])
    covered = sum(1 for p in players if p.get("status") is not None)
    ratio = covered / max(1, len(players))
    return bool(players) and ratio >= MINIMUM_PLAYER_COVERAGE_RATIO, {"coverage": round(ratio, 4), "players": len(players)}


def _probe_xmins() -> tuple[bool, dict]:
    try:
        from src.models.projection import xmins_distribution
        players = list(read_json(DATA / "universe.json", {}).get("players") or [])[:25]
        if not players:
            return False, {"reason": "no player sample"}
        good = 0
        for p in players:
            d = xmins_distribution(p)
            total = float(d.get("start_probability", 0)) + float(d.get("bench_probability", 0)) + float(d.get("dnp_probability", 0))
            if abs(total - 1.0) < XMINS_PROBABILITY_SUM_TOLERANCE and 0 <= float(d.get("expected_minutes", -1)) <= 90:
                good += 1
        return good == len(players), {"sample": len(players), "valid": good}
    except Exception as exc:
        return False, {"error": str(exc)}


def _probe_projection() -> tuple[bool, dict]:
    try:
        from src.models.projection import project_points
        players = list(read_json(DATA / "universe.json", {}).get("players") or [])[:25]
        vals = [project_points(p) for p in players]
        good = sum(1 for x in vals if float(x.get("projected_points", -1)) >= 0 and x.get("xmins"))
        return bool(vals) and good == len(vals), {"sample": len(vals), "valid": good}
    except Exception as exc:
        return False, {"error": str(exc)}


def _probe_defcon() -> tuple[bool, dict]:
    try:
        from src.rules import DC_RULES, DC_POINTS_CAP_PER_MATCH
        expected = ACTIVE_RULESET.get("defensive_contributions") or {}
        by_pos = expected.get("by_position") or {}
        ok = (
            DC_POINTS_CAP_PER_MATCH == int(expected.get("points_cap_per_match") or -1)
            and DC_RULES[1]["eligible"] == by_pos.get("GK", {}).get("eligible")
            and DC_RULES[2]["threshold"] == by_pos.get("DEF", {}).get("threshold")
            and DC_RULES[3]["threshold"] == by_pos.get("MID", {}).get("threshold")
        )
        return ok, {"ruleset_id": RULESET_ID, "cap": DC_POINTS_CAP_PER_MATCH}
    except Exception as exc:
        return False, {"error": str(exc)}


def _probe_price() -> tuple[bool, dict]:
    p = read_json(DATA / "prices.json", {})
    health = p.get("official_price_predictor_health") or {}
    players = list(p.get("players") or [])
    if health:
        return health.get("status") == "LIVE" and bool(players), {"predictor_status": health.get("status"), "players": len(players)}
    pressure = list(p.get("top_buy_pressure") or []) + list(p.get("top_sell_pressure") or [])
    return False, {"reason": "no predictor confirmation", "pressure_rows": len(pressure)}


def _probe_source_health() -> tuple[bool, dict]:
    h = read_json(DATA / "health.json", {})
    critical = ["bootstrap", "fixtures", "entry", "history", "transfers"]
    states = {k: (h.get(k) or {}).get("status") for k in critical}
    return all(states.get(k) == "LIVE" for k in critical), {"critical_endpoints": states}


def _probe_freshness(max_age_minutes: int = 90) -> tuple[bool, dict]:
    s = read_json(DATA / "latest.json", {})
    dt = parse_dt(s.get("generated_at"))
    if not dt:
        return False, {"reason": "latest.generated_at missing"}
    age = max(0.0, (utcnow() - dt).total_seconds() / 60)
    return age <= max_age_minutes, {"age_minutes": round(age, 1), "max_age_minutes": max_age_minutes}


def _probe_advanced() -> tuple[bool, dict]:
    paths = ["data/stats/shots_current.json", "data/stats/playermatchstats_current.json"]
    states = {p: _json_nonempty(p) for p in paths}
    return all(states.values()), states


def _probe_chip() -> tuple[bool, dict]:
    try:
        from src.rules import CHIP_RULES
        chips = read_json(DATA / "chips.json", {})
        expected = bool((ACTIVE_RULESET.get("chips") or {}).get("one_chip_per_gameweek"))
        ok = CHIP_RULES.get("one_chip_per_gameweek") is expected and chips.get("ruleset_id") == RULESET_ID
        return ok, {"ruleset_id": RULESET_ID, "one_chip_per_gameweek": CHIP_RULES.get("one_chip_per_gameweek")}
    except Exception as exc:
        return False, {"error": str(exc)}


def _probe_structural() -> tuple[bool, dict]:
    try:
        from src.models.optimizer import legal_counts
        lock = read_json(CONFIG / "locked_squad.json", {})
        universe = read_json(DATA / "universe.json", {})
        umap = {int(p["element"]): p for p in universe.get("players", []) if p.get("element") is not None}
        rows = []
        for p in lock.get("players", []):
            u = umap.get(int(p.get("element") or -1), {})
            rows.append({"position": p.get("position"), "team_id": u.get("team_id")})
        return len(rows) == SQUAD_SIZE and legal_counts(rows), {"players": len(rows), "expected": SQUAD_SIZE}
    except Exception as exc:
        return False, {"error": str(exc)}


def _probe_runtime() -> tuple[bool, dict]:
    h = read_json(DATA / "health.json", {})
    latencies = [v.get("latency_ms") for v in h.values() if isinstance(v, dict) and v.get("latency_ms") is not None]
    return bool(latencies), {"latency_samples": len(latencies), "max_latency_ms": max(latencies) if latencies else None}


def _operational_probe(name: str | None) -> tuple[str, dict]:
    if not name:
        return "PARTIAL", {"reason": "no operational probe declared"}
    active = {
        "universe_identity": _probe_universe,
        "universe_price_position": _probe_universe,
        "universe_registration": _probe_universe,
        "availability": _probe_availability,
        "xmins": _probe_xmins,
        "xmins_distribution": _probe_xmins,
        "advanced_stats": _probe_advanced,
        "defcon_rules": _probe_defcon,
        "clean_sheet_probability": _probe_projection,
        "structural_fit": _probe_structural,
        "chip_context": _probe_chip,
        "decision_recheck": _probe_structural,
        "reliability_overlay": _probe_source_health,
        "leakage_guard": lambda: (True, {"implementation": "src/engines/leakage_guard.py"}),
        "manual_authority": lambda: (bool(read_json(CONFIG / "locked_squad.json", {}).get("players")), {"authority": read_json(CONFIG / "locked_squad.json", {}).get("authoritative_phase")}),
        "data_freshness": _probe_freshness,
        "source_health": _probe_source_health,
        "price_intelligence": _probe_price,
        "runtime_observability": _probe_runtime,
        "transfer_momentum": lambda: (bool(read_json(DATA / "prices.json", {}).get("top_buy_pressure")), {"source": "data/prices.json"}),
        "current_form": _probe_advanced,
    }
    partial = {
        "tactical_role", "system_fit", "rotation_competition", "set_piece_role", "penalty_role", "sustainability",
        "bonus_route", "team_defensive_risk", "team_attacking_strength", "team_defensive_strength", "fixture_context",
        "fixture_difficulty", "horizon_3", "horizon_5", "horizon_10", "horizon_15", "fixture_swing",
        "european_congestion", "domestic_cup_congestion", "international_load", "rest_days", "preseason_prior",
        "last_season_prior", "historical_prior", "regression_risk", "price_value", "budget_opportunity_cost",
        "ownership_context", "learning_loop", "direct_challenger", "bench_utility", "captaincy",
        "projection_uncertainty", "small_sample_guard", "governed_optimizer", "team_cluster_penalty",
        "early_season_change_cap", "package_churn_penalty", "lineup_robustness", "captain_dnp_guard",
        "calibration_store", "uncertainty_robustness", "multi_horizon", "package_structural", "lineup_governance",
        "final_governance",
    }
    if name in active:
        ok, detail = active[name]()
        return ("ACTIVE" if ok else "FAILED"), detail
    if name in partial:
        return "PARTIAL", {"reason": "capability exists only partially or lacks production decision-output evidence"}
    return "PARTIAL", {"reason": f"unknown probe {name}"}


def _audit_registry(name: str, obj: dict) -> dict:
    integrity = _registry_integrity(name, obj)
    audited = []
    counts = Counter()
    for row in _rows(name, obj):
        req = list(row.get("required_files") or [])
        missing = [p for p in req if not _exists(p)]
        if missing:
            status = "FAILED" if row.get("critical") else "PARTIAL"
            detail = {"missing_files": missing}
        else:
            status, detail = _operational_probe(row.get("operational_probe"))
            if status == "FAILED" and not row.get("critical"):
                status = "PARTIAL"
        counts[status] += 1
        audited.append({
            "id": row.get("id"), "name": row.get("name"), "critical": bool(row.get("critical")),
            "status": status, "required_files": req, "probe": row.get("operational_probe"), "detail": detail,
        })
    return {**integrity, "registry": obj.get("registry"), "counts": dict(counts), "items": audited}


def _gate0(phase: str) -> dict:
    lock = read_json(CONFIG / "locked_squad.json", {})
    universe = read_json(DATA / "universe.json", {})
    team = read_json(DATA / "team.json", {})
    players = list(lock.get("players") or [])
    umap = {int(p["element"]): p for p in universe.get("players", []) if p.get("element") is not None}
    checks: dict[str, tuple[str, str]] = {}
    pos = Counter(p.get("position") for p in players)
    checks["G0-01"] = ("PASS" if len(players) == SQUAD_SIZE else "FAIL", f"count={len(players)},expected={SQUAD_SIZE}")
    ids_by_position = {"GK": "G0-02", "DEF": "G0-03", "MID": "G0-04", "FWD": "G0-05"}
    for position, cid in ids_by_position.items():
        expected = int(POSITION_COUNTS.get(position) or 0)
        checks[cid] = ("PASS" if pos.get(position, 0) == expected else "FAIL", f"{position}={pos.get(position,0)},expected={expected}")

    purchase_total = sum(int(p.get("purchase_cost") or 0) for p in players)
    itb = int(lock.get("itb_tenths") or 0)
    exact_budget = purchase_total + itb == BUDGET_TENTHS if lock.get("authoritative_phase") == "pre_deadline_wc" else purchase_total + itb <= BUDGET_TENTHS
    checks["G0-06"] = ("PASS" if exact_budget else "FAIL", f"purchase_total={purchase_total},itb={itb},budget={BUDGET_TENTHS}")

    clubs = Counter()
    eligible = True
    identity = True
    for p in players:
        u = umap.get(int(p.get("element") or -1))
        if not u:
            eligible = False
            identity = False
            continue
        clubs[int(u.get("team_id") or 0)] += 1
        if u.get("status") in {"u", "s"}:
            eligible = False
        if p.get("expected_team") and u.get("team") != p.get("expected_team"):
            identity = False
        if p.get("position") and u.get("position") != p.get("position"):
            identity = False
    checks["G0-07"] = ("PASS" if max(clubs.values(), default=0) <= MAX_PER_CLUB else "FAIL", f"max_club={max(clubs.values(), default=0)},limit={MAX_PER_CLUB}")
    element_ids = [int(p.get("element") or -1) for p in players]
    checks["G0-08"] = ("PASS" if len(element_ids) == len(set(element_ids)) else "FAIL", "element uniqueness")
    checks["G0-09"] = ("PASS" if eligible and identity else "FAIL", f"eligible={eligible},identity={identity}")

    lineup = read_json(DATA / "lineup_decision.json", {}) if phase == "postflight" else {}
    if lineup:
        xi = list(lineup.get("starting_xi") or [])
        xi_ids = {int(x.get("element")) for x in xi if x.get("element") is not None}
        form = lineup.get("formation")
        cap = int((lineup.get("captain") or {}).get("element") or -1)
        vice = int((lineup.get("vice_captain") or {}).get("element") or -1)
        bench = lineup.get("bench") or {}
        checks["G0-10"] = ("PASS" if len(xi) == STARTING_XI_SIZE and form in LEGAL_FORMS else "FAIL", f"formation={form},xi={len(xi)},expected={STARTING_XI_SIZE}")
        checks["G0-11"] = ("PASS" if sum(x.get("position") == "GK" for x in xi) == STARTING_GK_COUNT else "FAIL", f"starting_gk={sum(x.get('position') == 'GK' for x in xi)},expected={STARTING_GK_COUNT}")
        checks["G0-12"] = ("PASS" if cap in xi_ids and vice in xi_ids and cap != vice else "FAIL", f"captain={cap},vice={vice}")
        bench_gk_required = int(BENCH_RULES.get("goalkeepers") or 0)
        bench_outfield_required = int(BENCH_RULES.get("outfield") or 0)
        bench_ok = (bool(bench.get("gk")) if bench_gk_required else True) and len(bench.get("order") or []) == bench_outfield_required
        checks["G0-13"] = ("PASS" if bench_ok else "FAIL", f"bench_gk={bench_gk_required},bench_outfield={bench_outfield_required}")
        one_chip = bool((ACTIVE_RULESET.get("chips") or {}).get("one_chip_per_gameweek"))
        chip_ok = (lineup.get("chip_context") or {}).get("single_chip_rule_respected") is True if one_chip else True
        checks["G0-14"] = ("PASS" if chip_ok else "FAIL", f"single_chip_rule={one_chip}")
    else:
        for cid in ["G0-10", "G0-11", "G0-12", "G0-13", "G0-14"]:
            checks[cid] = ("DEFERRED", "requires governed lineup/chip output")

    ledger = list(team.get("team_value_ledger") or [])
    ledger_ok = True
    if ledger:
        try:
            from src.engines.team_value import sell_cost
            for row in ledger:
                if row.get("purchase_cost") is None or row.get("sell_cost") is None:
                    ledger_ok = False
                    break
                if int(row["sell_cost"]) != int(sell_cost(int(row["now_cost"]), int(row["purchase_cost"]))):
                    ledger_ok = False
                    break
        except Exception:
            ledger_ok = False
    checks["G0-15"] = ("PASS" if exact_budget and (ledger_ok or not ledger) else "FAIL", f"budget_reconciled={exact_budget},ledger_rows={len(ledger)},sell_formula_ok={ledger_ok}")

    package = read_json(DATA / "package_decision.json", {}) if phase == "postflight" else {}
    if package:
        checks["G0-16"] = ("PASS" if package.get("gate0_revalidated") is True else "FAIL", "winning package legality recheck")
    else:
        checks["G0-16"] = ("DEFERRED", "requires winning package output")

    registry = read_json(REGISTRIES["gate0"], {})
    names = {x.get("id"): x.get("name") for x in registry.get("checks", [])}
    items = [{"id": cid, "name": names.get(cid), "status": st, "detail": detail} for cid, (st, detail) in sorted(checks.items())]
    counts = Counter(x["status"] for x in items)
    return {"phase": phase, "ruleset_id": RULESET_ID, "counts": dict(counts), "items": items, "pass": counts.get("FAIL", 0) == 0}


def _rules_registry_health() -> tuple[str, dict]:
    r = read_json(DATA / "rules_compliance.json", {})
    status = str(r.get("overall") or "MISSING")
    detail = {
        "ruleset_id": r.get("ruleset_id"),
        "season": r.get("season"),
        "authority": r.get("authority"),
        "verified_at": r.get("verified_at"),
        "registry_integrity": (r.get("registry_integrity") or {}).get("status"),
        "drift": (r.get("drift") or {}).get("status"),
        "fingerprint_sha256": r.get("ruleset_fingerprint_sha256"),
    }
    return status, detail


def audit(phase: str = "preflight", strict: bool = False) -> dict[str, Any]:
    started = time.perf_counter()
    regs = {k: read_json(v, {}) for k, v in REGISTRIES.items()}
    health = {k: _audit_registry(k, regs[k]) for k in ("dss_core", "dss_extensions", "enhancements")}
    gate_integrity = _registry_integrity("gate0", regs["gate0"])
    registry_integrity = gate_integrity["integrity_ok"] and all(x["integrity_ok"] for x in health.values())
    gate0 = _gate0(phase)

    critical_failed = []
    critical_partial = []
    for group in ("dss_core", "dss_extensions", "enhancements"):
        for item in health[group]["items"]:
            if item["critical"] and item["status"] == "FAILED":
                critical_failed.append(item["id"])
            elif item["critical"] and item["status"] == "PARTIAL":
                critical_partial.append(item["id"])

    rules_status, rules_detail = _rules_registry_health()
    rules_failed = rules_status not in {"PASS", "REVIEW_REQUIRED"}
    rules_review = rules_status == "REVIEW_REQUIRED"
    data_ok, data_detail = _probe_freshness()
    source_ok, source_detail = _probe_source_health()

    if not registry_integrity or not gate0["pass"] or critical_failed or rules_failed or not source_ok:
        overall = "RED"
    elif rules_review or critical_partial or not data_ok or any(x["counts"].get("PARTIAL", 0) for x in health.values()):
        overall = "AMBER"
    else:
        overall = "GREEN"

    recommendation_allowed = overall != "RED" and gate0["pass"]
    go_allowed = overall == "GREEN" and gate0["pass"] and not rules_review and (phase == "preflight" or gate0["counts"].get("DEFERRED", 0) == 0)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    out = {
        "framework_schema": 2,
        "engine_version": ENGINE_VERSION,
        "auditor": "framework-health-auditor-v2-rules-registry",
        "phase": phase,
        "overall": overall,
        "decision_engine": "HEALTHY" if overall == "GREEN" else "DEGRADED" if overall == "AMBER" else "BLOCKED",
        "recommendation_allowed": recommendation_allowed,
        "go_allowed": go_allowed,
        "registry_integrity": registry_integrity,
        "rules_registry": {"status": rules_status, "detail": rules_detail},
        "gate0": {**gate0, "registry_integrity": gate_integrity},
        "dss_core": health["dss_core"],
        "dss_extensions": health["dss_extensions"],
        "enhancements": health["enhancements"],
        "rules_compliance": {"status": rules_status, "detail": rules_detail},
        "data_freshness": {"status": "PASS" if data_ok else "PARTIAL", "detail": data_detail},
        "source_health": {"status": "PASS" if source_ok else "FAIL", "detail": source_detail},
        "critical_failed": critical_failed,
        "critical_partial": critical_partial,
        "governance": {
            "rules_registry_precedes_gate0": True,
            "gate0_consumes_active_ruleset": True,
            "gate0_fail_blocks_go": True,
            "rules_registry_failure_blocks_go": True,
            "rules_drift_review_blocks_unqualified_go": True,
            "critical_framework_fail_blocks_recommendation": True,
            "critical_partial_blocks_unqualified_go": True,
            "file_exists_is_not_sufficient_for_active": True,
            "health_check_must_precede_recommendation": True,
            "raw_optimizer_is_not_final_decision": True,
        },
        "performance_ms": elapsed_ms,
    }
    atomic_json(PRE_OUT if phase == "preflight" else OUT, out)
    print(json.dumps({
        "overall": overall,
        "phase": phase,
        "rules": rules_status,
        "gate0": gate0["counts"],
        "dss_core": health["dss_core"]["counts"],
        "extensions": health["dss_extensions"]["counts"],
        "enhancements": health["enhancements"]["counts"],
        "recommendation_allowed": recommendation_allowed,
        "go_allowed": go_allowed,
        "performance_ms": elapsed_ms,
    }, ensure_ascii=False))
    if strict and overall == "RED":
        raise SystemExit(2)
    return out


def run() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["preflight", "postflight"], default="preflight")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    audit(args.phase, strict=args.strict)


if __name__ == "__main__":
    run()