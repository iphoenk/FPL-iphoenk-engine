from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.utils import DATA, CONFIG, atomic_json, read_json
from src.engines.v4_wc_optimizer import POSITION_COUNTS, BUDGET_TENTHS, MAX_PER_CLUB

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


def _exists(rel: str) -> bool:
    return (ROOT / rel).exists()


def _registry_rows(name: str, obj: dict) -> list[dict]:
    key = "modules" if name in {"dss_core", "dss_extensions"} else "layers" if name == "enhancements" else "checks"
    return list(obj.get(key) or [])


def _audit_registry(name: str, obj: dict) -> dict:
    rows = _registry_rows(name, obj)
    ids = [str(x.get("id")) for x in rows]
    duplicate_ids = sorted(k for k, v in Counter(ids).items() if v > 1)
    expected = EXPECTED_COUNTS[name]
    integrity_ok = len(rows) == expected and len(ids) == len(set(ids)) and all(ids)
    audited = []
    counts = Counter()
    for row in rows:
        req = list(row.get("required_files") or [])
        present = [p for p in req if _exists(p)]
        missing = [p for p in req if not _exists(p)]
        if not req:
            status = "DECLARED"
        elif not missing:
            status = "ACTIVE"
        elif present:
            status = "PARTIAL"
        else:
            status = "FAILED" if row.get("critical") else "PARTIAL"
        counts[status] += 1
        audited.append({
            "id": row.get("id"), "name": row.get("name"), "critical": bool(row.get("critical")),
            "status": status, "required_files": req, "missing_files": missing,
        })
    return {
        "registry": obj.get("registry"), "expected": expected, "declared": len(rows),
        "integrity_ok": integrity_ok, "duplicate_ids": duplicate_ids,
        "counts": dict(counts), "items": audited,
    }


def _gate0(phase: str, locked: dict, universe: dict, lineup: dict, packages: dict, compliance: dict) -> dict:
    checks: dict[str, tuple[str, str]] = {}
    players = list(locked.get("players") or [])
    counts = Counter(p.get("position") for p in players)
    checks["G0-01"] = ("PASS" if len(players) == 15 else "FAIL", f"count={len(players)}")
    checks["G0-02"] = ("PASS" if counts.get("GK") == 2 else "FAIL", f"GK={counts.get('GK',0)}")
    checks["G0-03"] = ("PASS" if counts.get("DEF") == 5 else "FAIL", f"DEF={counts.get('DEF',0)}")
    checks["G0-04"] = ("PASS" if counts.get("MID") == 5 else "FAIL", f"MID={counts.get('MID',0)}")
    checks["G0-05"] = ("PASS" if counts.get("FWD") == 3 else "FAIL", f"FWD={counts.get('FWD',0)}")

    purchase_total = sum(int(p.get("purchase_cost") or 0) for p in players)
    itb = int(locked.get("itb_tenths") or 0)
    checks["G0-06"] = ("PASS" if purchase_total + itb <= BUDGET_TENTHS else "FAIL", f"purchase_total={purchase_total},itb={itb}")

    umap = {int(p.get("element")): p for p in universe.get("players", []) if p.get("element") is not None}
    club_counts = Counter()
    eligible = True
    identity_ok = True
    current_cost = 0
    for p in players:
        u = umap.get(int(p.get("element")))
        if not u:
            eligible = False; identity_ok = False; continue
        club_counts[int(u.get("team_id") or 0)] += 1
        current_cost += int(u.get("now_cost") or 0)
        if u.get("status") in {"u", "s"}:
            eligible = False
        exp_team = p.get("expected_team")
        if exp_team and u.get("team") and str(exp_team) != str(u.get("team")):
            identity_ok = False
    checks["G0-07"] = ("PASS" if (not club_counts or max(club_counts.values()) <= MAX_PER_CLUB) else "FAIL", f"max_club={max(club_counts.values(), default=0)}")
    checks["G0-08"] = ("PASS" if len({int(p.get('element')) for p in players}) == len(players) else "FAIL", "element uniqueness")
    checks["G0-09"] = ("PASS" if eligible and identity_ok else "FAIL", f"eligible={eligible},identity_ok={identity_ok}")

    if lineup:
        xi = list(lineup.get("starting_xi") or [])
        form = lineup.get("formation")
        legal_forms = {"3-4-3","3-5-2","4-3-3","4-4-2","4-5-1","5-2-3","5-3-2","5-4-1"}
        xi_ids = {int(x.get("element")) for x in xi}
        cap = int((lineup.get("captain") or {}).get("element") or -1)
        vice = int((lineup.get("vice_captain") or {}).get("element") or -1)
        bench = lineup.get("bench") or {}
        checks["G0-10"] = ("PASS" if len(xi) == 11 and form in legal_forms else "FAIL", f"formation={form},xi={len(xi)}")
        checks["G0-11"] = ("PASS" if sum(x.get("position") == "GK" for x in xi) == 1 else "FAIL", "starting GK")
        checks["G0-12"] = ("PASS" if cap in xi_ids and vice in xi_ids and cap != vice else "FAIL", f"captain={cap},vice={vice}")
        checks["G0-13"] = ("PASS" if bool(bench.get("gk")) and len(bench.get("order") or []) == 3 else "FAIL", "bench structure")
        chip_ok = bool((lineup.get("chip_context") or {}).get("single_chip_rule_respected"))
        checks["G0-14"] = ("PASS" if chip_ok and compliance.get("overall") == "PASS" else "FAIL", f"single_chip={chip_ok},rules={compliance.get('overall')}")
    else:
        for cid in ["G0-10","G0-11","G0-12","G0-13"]:
            checks[cid] = ("DEFERRED", "requires lineup output")
        checks["G0-14"] = ("PASS" if compliance.get("overall") == "PASS" else "DEFERRED", f"rules={compliance.get('overall')}")

    arithmetic_ok = (purchase_total + itb == BUDGET_TENTHS) if locked.get("authoritative_phase") == "pre_deadline_wc" else (purchase_total + itb <= BUDGET_TENTHS)
    checks["G0-15"] = ("PASS" if arithmetic_ok else "FAIL", f"purchase_total+itb={purchase_total+itb};current_cost={current_cost}")

    if packages:
        budget = int((packages.get("guardrails") or {}).get("budget_tenths") or BUDGET_TENTHS)
        legal = True
        seen = 0
        for rows in (packages.get("packages") or {}).values():
            for row in rows or []:
                seen += 1
                if int(row.get("target_cost") or budget + 1) > budget:
                    legal = False; break
        checks["G0-16"] = ("PASS" if legal and seen > 0 else "FAIL", f"packages_checked={seen}")
    else:
        checks["G0-16"] = ("DEFERRED", "requires package audit output")

    registry = read_json(REGISTRIES["gate0"], {})
    names = {x.get("id"): x.get("name") for x in registry.get("checks", [])}
    items = [{"id": cid, "name": names.get(cid), "status": st, "detail": detail} for cid, (st, detail) in sorted(checks.items())]
    cnt = Counter(x["status"] for x in items)
    return {"phase": phase, "counts": dict(cnt), "items": items, "pass": cnt.get("FAIL", 0) == 0}


def audit(phase: str = "postflight") -> dict:
    regs = {k: read_json(v, {}) for k, v in REGISTRIES.items()}
    registry_health = {k: _audit_registry(k, v) for k, v in regs.items()}
    integrity_ok = all(x["integrity_ok"] for x in registry_health.values())

    locked = read_json(CONFIG / "locked_squad.json", {})
    universe = read_json(DATA / "universe.json", {})
    compliance = read_json(DATA / "compliance_audit.json", {})
    lineup = read_json(DATA / "lineup_decision_v4.json", {}) if phase == "postflight" else {}
    packages = read_json(DATA / "wc_package_audit_v4.json", {}) if phase == "postflight" else {}
    gate0 = _gate0(phase, locked, universe, lineup, packages, compliance)

    critical_failed = []
    critical_partial = []
    for group in ("dss_core", "dss_extensions", "enhancements"):
        for item in registry_health[group]["items"]:
            if item["critical"] and item["status"] == "FAILED": critical_failed.append(item["id"])
            elif item["critical"] and item["status"] == "PARTIAL": critical_partial.append(item["id"])

    if not integrity_ok or not gate0["pass"] or critical_failed:
        overall = "RED"
    elif critical_partial:
        overall = "AMBER"
    else:
        overall = "GREEN"

    out = {
        "schema_version": 4601,
        "engine": "v4.6-framework-health-auditor",
        "phase": phase,
        "overall": overall,
        "go_allowed": overall != "RED" and gate0["pass"],
        "registry_integrity": integrity_ok,
        "gate0": gate0,
        "dss_core": registry_health["dss_core"],
        "dss_extensions": registry_health["dss_extensions"],
        "enhancements": registry_health["enhancements"],
        "critical_failed": critical_failed,
        "critical_partial": critical_partial,
        "reporting_contract": {
            "health_check_first": True,
            "raw_optimizer_distinct_from_governed_recommendation": True,
            "manual_draft_distinct_from_final_lock": True,
            "gate0_fail_blocks_go": True,
        },
    }
    atomic_json(PRE_OUT if phase == "preflight" else OUT, out)
    print(json.dumps({
        "framework_health": overall,
        "phase": phase,
        "gate0": gate0["counts"],
        "dss_core": registry_health["dss_core"]["counts"],
        "extensions": registry_health["dss_extensions"]["counts"],
        "enhancements": registry_health["enhancements"]["counts"],
        "go_allowed": out["go_allowed"],
    }, ensure_ascii=False))
    if overall == "RED":
        raise SystemExit(2)
    return out


def run():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["preflight", "postflight"], default="postflight")
    args = ap.parse_args()
    return audit(args.phase)


if __name__ == "__main__":
    run()
