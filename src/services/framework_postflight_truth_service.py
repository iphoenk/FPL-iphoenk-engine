from __future__ import annotations

import json
from collections import Counter

from src.engines import framework_health_audit as audit
from src.utils import DATA, atomic_json, read_json

LEGAL_FORMS = {"3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-2-3", "5-3-2", "5-4-1"}


def _plan_checks(plan: dict, compliance: dict | None = None) -> dict[str, tuple[bool, str]]:
    xi = list(plan.get("starting_xi") or [])
    xi_ids = {int(row.get("element")) for row in xi if row.get("element") is not None}
    captain = int((plan.get("captain") or {}).get("element") or -1)
    vice = int((plan.get("vice_captain") or {}).get("element") or -1)
    bench = plan.get("bench") or {}
    chip = plan.get("chip_context") or {}
    checks = {
        "G0-10": (len(xi) == 11 and plan.get("formation") in LEGAL_FORMS, f"formation={plan.get('formation')},xi={len(xi)}"),
        "G0-11": (sum(row.get("position") == "GK" for row in xi) == 1, "starting GK"),
        "G0-12": (captain in xi_ids and vice in xi_ids and captain != vice, f"captain={captain},vice={vice}"),
        "G0-13": (bool(bench.get("gk")) and len(bench.get("order") or []) == 3, "bench structure"),
        "G0-14": (chip.get("single_chip_rule_respected") is True and (not compliance or compliance.get("overall") == "PASS"), f"single_chip={chip.get('single_chip_rule_respected')},rules={(compliance or {}).get('overall')}"),
    }
    return checks


def run() -> dict:
    health = audit.audit("postflight", strict=False)
    engine_plan = read_json(DATA / "lineup_decision_v4.json", {})
    overlay = read_json(DATA / "effective_plan_v4.json", {})
    effective_plan = overlay.get("effective_plan") or {}
    compliance = read_json(DATA / "compliance_audit.json", {})
    if not engine_plan or not effective_plan:
        raise RuntimeError("postflight truth service requires engine and effective plans")

    engine_checks = _plan_checks(engine_plan, compliance)
    effective_checks = _plan_checks(effective_plan, compliance)
    items = list((health.get("gate0") or {}).get("items") or [])
    by_id = {row.get("id"): row for row in items}
    for check_id in ("G0-10", "G0-11", "G0-12", "G0-13", "G0-14"):
        engine_ok, engine_detail = engine_checks[check_id]
        effective_ok, effective_detail = effective_checks[check_id]
        row = by_id.get(check_id)
        if row is None:
            raise RuntimeError(f"Gate-0 row missing: {check_id}")
        row["status"] = "PASS" if engine_ok and effective_ok else "FAIL"
        row["detail"] = f"engine[{engine_detail}];effective[{effective_detail}]"

    counts = Counter(row.get("status") for row in items)
    gate0_pass = counts.get("FAIL", 0) == 0
    health["gate0"]["counts"] = dict(counts)
    health["gate0"]["pass"] = gate0_pass
    health["gate0"]["plan_authority_validation"] = {
        "engine_plan": {
            "authority": "ENGINE_RECOMMENDATION",
            "formation": engine_plan.get("formation"),
            "legal": all(value[0] for value in engine_checks.values()),
        },
        "effective_plan": {
            "authority": effective_plan.get("authority") or overlay.get("decision_authority") or "UNKNOWN",
            "formation": effective_plan.get("formation"),
            "legal": all(value[0] for value in effective_checks.values()),
        },
        "both_required": True,
    }
    health.setdefault("governance", {})["effective_plan_legality_enforced"] = True
    health["governance"]["engine_and_effective_plan_legality_reported_separately"] = True
    health["release"] = "4.9.4.3"

    if not gate0_pass:
        health["overall"] = "RED"
        health["pipeline_health"] = "RED"
        health["recommendation_allowed"] = False
        health["go_allowed"] = False

    atomic_json(DATA / "framework_health_v4.json", health)
    print(json.dumps({
        "service": "framework_postflight",
        "pipeline_health": health.get("pipeline_health"),
        "gate0": health["gate0"]["counts"],
        "engine_formation": engine_plan.get("formation"),
        "effective_formation": effective_plan.get("formation"),
        "both_legal": gate0_pass,
    }, ensure_ascii=False))
    if health.get("overall") == "RED":
        raise SystemExit(2)
    return health


if __name__ == "__main__":
    run()
