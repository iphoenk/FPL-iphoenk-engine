from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_policy():
    path = CONFIG / "challenger_comparator.json"
    obj = load(path)
    screening = obj.setdefault("screening", {})
    screening["owned_minutes_risk_start_probability"] = 0.72
    screening["maximum_raw_to_shrunk_ratio_for_sustainable"] = 2.5
    obj.setdefault("confidence_weights", {
        "core_completeness": 0.58,
        "start_security": 0.22,
        "tactical_evidence": 0.10,
        "congestion_evidence": 0.10,
    })
    dump(path, obj)


def patch_service_source():
    path = ROOT / "src" / "services" / "challenger_comparator_service.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        '    if f(sustainability.get("raw_to_shrunk_ratio"), 99) > 2.5:\n',
        '    maximum_ratio = f((policy.get("screening") or {}).get("maximum_raw_to_shrunk_ratio_for_sustainable"), 2.5)\n'
        '    if f(sustainability.get("raw_to_shrunk_ratio"), 99) > maximum_ratio:\n',
    )
    text = text.replace(
        '        if owned_start is not None and owned_start < 0.72:\n',
        '        minutes_risk = f((policy.get("screening") or {}).get("owned_minutes_risk_start_probability"), 0.72)\n'
        '        if owned_start is not None and owned_start < minutes_risk:\n',
    )
    old = '''    return {\n        "tactical_role": priors.get("tactical_role") or (first.get("calibration") or {}).get("tactical_role"),\n'''
    new = '''    start_series = [f((row.get("xmins") or {}).get("start_probability")) for row in fixtures[:5]]\n    minute_series = [f((row.get("xmins") or {}).get("expected_minutes")) for row in fixtures[:5]]\n    start_trend = round(start_series[-1] - start_series[0], 4) if len(start_series) >= 2 else None\n    minute_trend = round(minute_series[-1] - minute_series[0], 1) if len(minute_series) >= 2 else None\n    return {\n        "tactical_role": priors.get("tactical_role") or (first.get("calibration") or {}).get("tactical_role"),\n'''
    if old not in text:
        raise RuntimeError("role sustainability insertion anchor missing")
    text = text.replace(old, new, 1)
    text = text.replace(
        '        "dnp_probability_3gw": round(dnp, 4) if dnp is not None else None,\n',
        '        "dnp_probability_3gw": round(dnp, 4) if dnp is not None else None,\n'
        '        "start_probability_trend_5gw": start_trend,\n'
        '        "expected_minutes_trend_5gw": minute_trend,\n',
        1,
    )
    old_conf = '''    confidence = clamp(\n        0.58 * core_completeness\n        + 0.22 * (screening.get("start_probability_3gw") or 0)\n        + 0.10 * min(1.0, tactical_verified / 3.0)\n        + 0.10 * min(1.0, congestion_verified / 3.0)\n    )\n'''
    new_conf = '''    confidence_weights = policy.get("confidence_weights") or {}\n    confidence = clamp(\n        f(confidence_weights.get("core_completeness"), 0.58) * core_completeness\n        + f(confidence_weights.get("start_security"), 0.22) * (screening.get("start_probability_3gw") or 0)\n        + f(confidence_weights.get("tactical_evidence"), 0.10) * min(1.0, tactical_verified / 3.0)\n        + f(confidence_weights.get("congestion_evidence"), 0.10) * min(1.0, congestion_verified / 3.0)\n    )\n'''
    if old_conf not in text:
        raise RuntimeError("confidence anchor missing")
    text = text.replace(old_conf, new_conf, 1)
    old_watch = '''        "watchlist_governance_suggestion": (\n            "PROMOTE_TO_WATCHLIST" if decision == "PROMOTE_TO_WATCHLIST" else "NO_AUTOMATIC_WATCHLIST_MUTATION"\n        ),\n'''
    new_watch = '''        "watchlist_governance_suggestion": (\n            "PROMOTE_TO_WATCHLIST"\n            if decision == "PROMOTE_TO_WATCHLIST"\n            else "REVIEW_DEMOTION"\n            if challenger.get("challenger_type") == "GOVERNED_WATCHLIST" and (not screening.get("pass") or raw_gain5 <= 0)\n            else "KEEP_OR_REPRIORITIZE"\n            if challenger.get("challenger_type") == "GOVERNED_WATCHLIST"\n            else "NO_AUTOMATIC_WATCHLIST_MUTATION"\n        ),\n'''
    if old_watch not in text:
        raise RuntimeError("watchlist governance anchor missing")
    text = text.replace(old_watch, new_watch, 1)
    text = text.replace('"engine": "v4.9.7-owned-challenger-comparator",', '"engine": "v4.9.6-owned-challenger-comparator",')
    path.write_text(text, encoding="utf-8")


def patch_service_registry():
    path = CONFIG / "service_registry.json"
    obj = load(path)
    services = obj.get("services") or []
    if not any(row.get("id") == "challenger_comparator" for row in services):
        report_index = next(i for i, row in enumerate(services) if row.get("id") == "report_governance")
        services.insert(report_index, {
            "id": "challenger_comparator",
            "name": "Generic OWNED vs Challenger Comparator Service",
            "boundary_state": "INDEPENDENT",
            "module": "src.services.challenger_comparator_service",
            "command": ["{python}", "-m", "src.services.challenger_comparator_service"],
            "timeout_seconds": 25,
            "depends_on": ["user_decision_overlay"],
            "produces": ["challenger_comparator"],
            "critical": True,
        })
    report = next(row for row in services if row.get("id") == "report_governance")
    deps = list(report.get("depends_on") or [])
    if "challenger_comparator" not in deps:
        deps.append("challenger_comparator")
    report["depends_on"] = deps
    obj["services"] = services
    guards = obj.setdefault("guardrails", {})
    guards.update({
        "service_count": len(services),
        "challenger_comparator_process_isolated": True,
        "challenger_comparator_advisory_only": True,
        "challenger_comparator_no_official_refetch": True,
        "challenger_comparator_reuses_canonical_predictions": True,
        "challenger_comparator_reuses_canonical_legality_and_price": True,
        "challenger_comparator_recent_haul_trigger_not_transfer": True,
        "challenger_comparator_never_overwrites_effective_plan": True,
        "challenger_comparator_never_mutates_watchlist": True,
        "challenger_comparator_missing_evidence_fail_safe": True,
    })
    dump(path, obj)


def patch_contract_registry():
    path = CONFIG / "service_contract_registry.json"
    obj = load(path)
    obj["schema_version"] = max(int(obj.get("schema_version") or 0), 9)
    contracts = obj.setdefault("contracts", {})
    contracts["challenger_comparator"] = {
        "path": "data/challenger_comparator_v4.json",
        "min_schema_version": 497,
        "version_field": "engine",
        "version_prefix": "v4.9.6-owned-challenger-comparator",
        "required_paths": [
            "status",
            "capability_state",
            "planning_gw",
            "challenger_universe.emerging_trigger_is_not_transfer",
            "candidate_summaries",
            "comparisons",
            "summary.decision_counts",
            "evidence_governance.official_facts_source",
            "guardrails.process_isolated_microservice",
            "guardrails.official_api_refetch",
            "guardrails.advisory_only",
            "guardrails.recent_haul_is_discovery_signal_only",
            "guardrails.canonical_xpts_reused",
            "guardrails.canonical_xmins_reused",
            "guardrails.canonical_fixture_projection_reused",
            "guardrails.canonical_price_and_legality_reused",
            "guardrails.canonical_role_sustainability_reused",
            "guardrails.watchlist_screening_not_reimplemented",
            "guardrails.effective_plan_mutated",
            "guardrails.optimizer_recommendation_mutated",
            "guardrails.watchlist_mutated",
            "guardrails.lineup_captain_chip_mutated",
            "guardrails.missing_evidence_never_fabricated",
            "guardrails.majority_voting"
        ],
        "equals": {
            "status": "PASS",
            "capability_state": "ADVISORY_ONLY",
            "challenger_universe.emerging_trigger_is_not_transfer": True,
            "guardrails.process_isolated_microservice": True,
            "guardrails.official_api_refetch": False,
            "guardrails.advisory_only": True,
            "guardrails.recent_haul_is_discovery_signal_only": True,
            "guardrails.canonical_xpts_reused": True,
            "guardrails.canonical_xmins_reused": True,
            "guardrails.canonical_fixture_projection_reused": True,
            "guardrails.canonical_price_and_legality_reused": True,
            "guardrails.canonical_role_sustainability_reused": True,
            "guardrails.watchlist_screening_not_reimplemented": True,
            "guardrails.effective_plan_mutated": False,
            "guardrails.optimizer_recommendation_mutated": False,
            "guardrails.watchlist_mutated": False,
            "guardrails.lineup_captain_chip_mutated": False,
            "guardrails.missing_evidence_never_fabricated": True,
            "guardrails.majority_voting": False
        },
        "min_lengths": {"candidate_summaries": 1, "comparisons": 1}
    }
    dump(path, obj)


def patch_ownership_registry():
    path = CONFIG / "architecture_ownership_registry.json"
    obj = load(path)
    responsibilities = obj.setdefault("responsibilities", [])
    if not any(row.get("id") == "OWNED_CHALLENGER_COMPARISON" for row in responsibilities):
        responsibilities.append({
            "id": "OWNED_CHALLENGER_COMPARISON",
            "owner": "challenger_comparator",
            "implementation": "src.services.challenger_comparator_service",
        })
    shared = obj.setdefault("shared_primitives", [])
    if not any(row.get("id") == "CHALLENGER_COMPARISON_ORCHESTRATION" for row in shared):
        shared.append({
            "id": "CHALLENGER_COMPARISON_ORCHESTRATION",
            "owner": "challenger_comparator",
            "implementation": "src.services.challenger_comparator_service",
            "consumers": ["report_governance", "master_monitor"],
            "reuses": [
                "XMINS_DISTRIBUTION",
                "MULTI_HORIZON_PROJECTION",
                "PRICE_MARKET_EVIDENCE",
                "RATE_SHRINKAGE_SUSTAINABILITY",
                "FIXTURE_RUN_SUMMARY",
                "PLAN_AND_SQUAD_LEGALITY"
            ]
        })
    dump(path, obj)


def patch_readme():
    path = ROOT / "README.md"
    text = path.read_text(encoding="utf-8")
    heading = "## V4 generic OWNED vs challenger comparator"
    if heading in text:
        return
    text += f'''\n\n{heading}\n\n- Adds a process-isolated, `ADVISORY_ONLY` comparator for any OWNED player versus governed candidates and performance-triggered emerging challengers.\n- A recent haul is discovery evidence only; it can create `EMERGING_CHALLENGER` but never directly creates a BUY/TRANSFER instruction.\n- The comparator reuses canonical V4 prediction, xMins, fixture-run, price/sell-value, squad-legality, rate-shrinkage and user-plan artifacts; it does not create second xPts/xMins/fixture/price/role engines.\n- Official fixture identity is read from the immutable raw snapshot without API refetch. Missing opponent tactical structure, all-competition congestion, international context or external consensus is explicitly `UNVERIFIED` rather than fabricated.\n- Runtime output is `data/challenger_comparator_v4.json`. It exposes 1/2/3/5-GW comparisons, fixture-by-fixture projections, affordability, uncertainty, sustainability, decision risks and reversal triggers.\n- V4 does not currently materialize an authoritative watchlist by default. If `data/watchlist_v4.json` is absent, engine-governed DSS candidates are clearly labelled `GOVERNED_DSS_CANDIDATE` rather than falsely called watchlist candidates.\n- Allowed advisory classifications are `HOLD_OWNED`, `WATCH_CHALLENGER`, `PROMOTE_TO_WATCHLIST`, `REVIEW`, `LEAN_TRANSFER`, and `STRONG_TRANSFER`; comparator output never overwrites the canonical optimizer, effective user plan, XI, C/VC, chip or watchlist.\n'''
    path.write_text(text, encoding="utf-8")


def main():
    patch_policy()
    patch_service_source()
    patch_service_registry()
    patch_contract_registry()
    patch_ownership_registry()
    patch_readme()
    print("V4 challenger comparator migration applied")


if __name__ == "__main__":
    main()
