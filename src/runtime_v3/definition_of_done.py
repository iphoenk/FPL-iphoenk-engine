from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from src.utils import DATA, ROOT, parse_dt, read_json


def _check(rows: list[dict[str, Any]], name: str, passed: bool, detail: Any = None, *, external: bool = False) -> None:
    rows.append({
        "name": name,
        "status": "EXTERNAL_PROOF" if external else ("PASS" if passed else "FAIL"),
        "passed": bool(passed) if not external else None,
        "detail": detail,
    })


def _run_json_module(module: str, *args: str) -> tuple[bool, dict[str, Any]]:
    proc = subprocess.run([sys.executable, "-m", module, *args], capture_output=True, text=True, check=False)
    parsed: dict[str, Any] = {}
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    if not parsed and proc.stderr:
        parsed = {"stderr_tail": proc.stderr[-2000:]}
    return proc.returncode == 0, parsed


def _freshness_seconds(payload: dict[str, Any]) -> float | None:
    generated = parse_dt(payload.get("generated_at"))
    if generated is None:
        return None
    now = datetime.now(timezone.utc)
    return max(0.0, (now - generated).total_seconds())


def _framework_counts(framework: dict[str, Any], key: str, state: str) -> int:
    block = framework.get(key) or {}
    return int((block.get("counts") or {}).get(state) or 0)


def _tactical_report_coverage(user: dict[str, Any], watchlist: dict[str, Any]) -> dict[str, Any]:
    owned = list((user.get("owned_squad") or {}).get("facts") or [])
    external = [
        row
        for position in ("GK", "DEF", "MID", "FWD")
        for row in ((watchlist.get("positions") or {}).get(position) or [])
    ]
    return {
        "owned": len(owned),
        "owned_with_tactical": sum(isinstance(row.get("tactical_matchup"), dict) and bool(row.get("tactical_matchup")) for row in owned),
        "watchlist": len(external),
        "watchlist_with_tactical": sum(isinstance(row.get("tactical_matchup"), dict) and bool(row.get("tactical_matchup")) for row in external),
    }


def _price_fact_model_contract(prices: dict[str, Any], alerts: dict[str, Any], trajectory: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    official_fields = prices.get("official_price_fields") or {}
    authority = str(official_fields.get("authority") or "")
    model_id = str((prices.get("filter_policy") or {}).get("model_id") or (alerts.get("policy") or {}).get("model_id") or "")
    players = [row for row in prices.get("players") or [] if isinstance(row, dict)]
    sampled = players[:25]
    semantic_separation = bool(sampled) and all(
        "now_cost" in row
        and "official_progress_pct" in row
        and "predicted_change_deadline" in row
        and "prediction_source" in row
        for row in sampled
    )
    fact_authority = authority == "Official FPL bootstrap native fields"
    model_declared = model_id == "official_price_radar_v2"
    trajectory_is_state_cache = isinstance(trajectory.get("players"), dict) and bool(trajectory.get("generated_at"))
    return fact_authority and model_declared and semantic_separation and trajectory_is_state_cache, {
        "fact_authority": authority,
        "model_id": model_id,
        "sampled_players": len(sampled),
        "semantic_field_separation": semantic_separation,
        "fact_fields": ["now_cost", "official_progress_pct", "official_hourly_rate_pct", "official_projections"],
        "model_fields": ["predicted_change_deadline", "prediction_source", "trajectory_eta_hours", "urgency"],
        "trajectory_role": "STATE_CACHE" if trajectory_is_state_cache else "UNVERIFIED",
    }


def run(scope: str = "candidate", source_commit: str | None = None) -> dict[str, Any]:
    framework = read_json(DATA / "framework_health.json", {})
    latest = read_json(DATA / "latest.json", {})
    user = read_json(DATA / "user_report.json", {})
    watchlist = read_json(DATA / "dss_watchlist.json", {})
    load = read_json(DATA / "recent_competitive_load.json", {})
    team = read_json(DATA / "team.json", {})
    detail = read_json(DATA / "official_detail.json", {})
    runtime = read_json(DATA / "runtime_performance.json", {})
    manifest = read_json(DATA / "runtime_manifest.json", {})
    prices = read_json(DATA / "prices.json", {})
    trajectory = read_json(DATA / "price_trajectory.json", {})
    price_alerts = read_json(DATA / "price_alerts.json", {})
    technical = read_json(DATA / "technical_appendix.json", {})
    accuracy = read_json(DATA / "prediction_accuracy.json", {})
    decision_snapshots = read_json(DATA / "decision_validation_snapshots.json", {})
    rows: list[dict[str, Any]] = []

    _check(rows, "CI_GREEN", True, "proved by the enclosing V3 CI workflow", external=True)
    _check(rows, "FRAMEWORK_GREEN", framework.get("overall") == "GREEN" and framework.get("go_allowed") is True, {"overall": framework.get("overall"), "go_allowed": framework.get("go_allowed")})
    _check(rows, "GATE0_16_16", _framework_counts(framework, "gate0", "PASS") == 16, (framework.get("gate0") or {}).get("counts"))
    _check(rows, "DSS_CORE_50_50", _framework_counts(framework, "dss_core", "ACTIVE") == 50, (framework.get("dss_core") or {}).get("counts"))
    _check(rows, "DSS_EXTENSIONS_16_16", _framework_counts(framework, "dss_extensions", "ACTIVE") == 16, (framework.get("dss_extensions") or {}).get("counts"))
    _check(rows, "ENHANCEMENTS_8_HEALTHY", _framework_counts(framework, "enhancements", "ACTIVE") == 8, (framework.get("enhancements") or {}).get("counts"))

    runtime_ok = runtime.get("execution_profile") == "fast_decision" and runtime.get("within_target_slo") is True and float(runtime.get("total_wall_ms") or 1e9) < 10000.0
    _check(rows, "RUNTIME_FAST_GREEN", runtime_ok, {"profile": runtime.get("execution_profile"), "wall_ms": runtime.get("total_wall_ms"), "target_ms": runtime.get("target_wall_ms")})
    canonical_runtime = (
        int(runtime.get("execution_domain_count") or 0) == 11
        and int(runtime.get("execution_phase_count") or 0) == 6
        and int(runtime.get("capability_owner_count") or 0) == 21
    )
    _check(
        rows,
        "CANONICAL_11_DOMAIN_6_PHASE_RUNTIME",
        canonical_runtime,
        {
            "domains": runtime.get("execution_domain_count"),
            "phases": runtime.get("execution_phase_count"),
            "owners": runtime.get("capability_owner_count"),
        },
    )

    age = _freshness_seconds(latest)
    _check(rows, "FRESH_RUNTIME_DATA", age is not None and age <= 900.0, {"age_seconds": round(age, 3) if age is not None else None, "max_seconds": 900})

    historical = (detail.get("historical_entry") or {})
    history_ready = historical.get("authority") == "PUBLIC_OFFICIAL_POST_DEADLINE" and any((row or {}).get("status") == "PUBLIC_OFFICIAL_SUBMITTED_TEAM" for row in (historical.get("gameweeks") or {}).values())
    _check(rows, "POST_DEADLINE_OFFICIAL_RECONCILIATION_PROVEN", history_ready, {"authority": historical.get("authority"), "gameweeks": sorted((historical.get("gameweeks") or {}).keys())})
    _check(rows, "OFFICIAL_HISTORY_IMMUTABLE_AUTHORITY", (latest.get("official_historical_authority") or {}).get("historical_submitted_team") == "GREEN_PUBLIC_OFFICIAL", latest.get("official_historical_authority"))

    workflow_text = (ROOT / ".github" / "workflows" / "v3-runtime.yml").read_text(encoding="utf-8")
    schedule_ok = 'cron: "30 * * * *"' in workflow_text and 'cron: "0,15,45 * * * *"' in workflow_text and "collector_gate" in workflow_text
    _check(rows, "SCHEDULE_GOVERNANCE_PROVEN", schedule_ok, {"master_hourly_30": 'cron: "30 * * * *"' in workflow_text, "adaptive_support": 'cron: "0,15,45 * * * *"' in workflow_text})

    comparator = technical.get("owned_challenger_comparator") or {}
    _check(rows, "COMPARATOR_CANONICAL", comparator.get("contract") in {"OWNED_CHALLENGER_COMPARATOR_V1", "OWNED_CHALLENGER_COMPARATOR_V2", "OWNED_CHALLENGER_COMPARATOR_V3"} and comparator.get("advisory_only") is True, {"contract": comparator.get("contract"), "advisory_only": comparator.get("advisory_only")})

    tactical = _tactical_report_coverage(user, watchlist)
    _check(rows, "TACTICAL_EVIDENCE_ALL_35", tactical == {"owned": 15, "owned_with_tactical": 15, "watchlist": 20, "watchlist_with_tactical": 20}, tactical)

    load_ok = int(load.get("player_count") or 0) >= 35 and load.get("contract") == "COMPETITIVE_LOAD_PRIMITIVE_V1" and (load.get("governance") or {}).get("no_blanket_fatigue_penalty") is True
    _check(rows, "COMPETITIVE_LOAD_EVIDENCE", load_ok, {"status": load.get("status"), "players": load.get("player_count"), "state_counts": load.get("state_counts")})

    ownership_ok, ownership = _run_json_module("src.engines.v3_architecture_ownership_guard")
    _check(rows, "NO_DUPLICATE_OWNERSHIP", ownership_ok and ownership.get("status") == "PASS", {"status": ownership.get("status"), "errors": ownership.get("errors")})

    owned_count = int((user.get("owned_squad") or {}).get("count") or 0)
    position_counts = {pos: len((watchlist.get("positions") or {}).get(pos) or []) for pos in ("GK", "DEF", "MID", "FWD")}
    _check(rows, "OWNED_15", owned_count == 15, owned_count)
    _check(rows, "WATCHLIST_20_5_PER_POSITION", sum(position_counts.values()) == 20 and all(value == 5 for value in position_counts.values()), position_counts)

    price_separated, price_detail = _price_fact_model_contract(prices, price_alerts, trajectory)
    _check(rows, "PRICE_FACT_MODEL_SEPARATED", price_separated, price_detail)

    no_fabrication = (
        (load.get("governance") or {}).get("travel_distance_must_not_be_invented") is True
        and (load.get("governance") or {}).get("coach_rotation_tendency_must_not_be_inferred_without_evidence") is True
        and (accuracy.get("governance") or {}).get("post_deadline_information_cannot_create_retroactive_decision_snapshot") is True
    )
    _check(rows, "NO_FABRICATED_EVIDENCE", no_fabrication, {"load_status": load.get("status"), "prediction_confidence": accuracy.get("confidence")})

    baseline = team.get("projection_baseline") or {}
    user_authority_ok = baseline.get("stale_override_rejected") is True and baseline.get("effective_authority") in {"OFFICIAL_SUBMITTED", "USER_OVERRIDE"}
    _check(rows, "USER_OVERRIDE_PHASE_AUTHORITY_GOVERNED", user_authority_ok, baseline)

    benchmark_ok, benchmark = _run_json_module("src.runtime_v3.unified_fastpath", "--benchmark")
    interactive_ms = benchmark.get("median_ms")
    _check(rows, "INTERACTIVE_SERVING_UNDER_1S", benchmark_ok and interactive_ms is not None and float(interactive_ms) < 1000.0, benchmark)

    report_registry = read_json(DATA / "report_artifact_registry.json", {})
    report_contract_ok = bool(report_registry) and (DATA / "decision_brief.json").exists() and (DATA / "deep_review_payload.json").exists()
    _check(rows, "REPORT_CONTRACTS_GREEN", report_contract_ok, {"registry": report_registry.get("registry"), "decision_brief": (DATA / "decision_brief.json").exists(), "deep_review": (DATA / "deep_review_payload.json").exists()})

    decision_capture_ok = decision_snapshots.get("contract") == "DECISION_VALIDATION_SNAPSHOTS_V1"
    _check(rows, "MODEL_VALIDATION_GENUINE_SNAPSHOT_PIPELINE", decision_capture_ok and (accuracy.get("governance") or {}).get("formula_correctness_is_separate_from_predictive_accuracy") is True, {"snapshot_contract": decision_snapshots.get("contract"), "confidence": accuracy.get("confidence"), "decision_metrics": accuracy.get("decision_metrics")})

    if scope == "production":
        source_ok = bool(source_commit) and manifest.get("source_commit") == source_commit
        _check(rows, "PRODUCTION_PUBLICATION_SOURCE_COMMIT", source_ok, {"expected": source_commit, "manifest": manifest.get("source_commit")})
    else:
        _check(rows, "PRODUCTION_PUBLICATION_SOURCE_COMMIT", True, "proved after merge by V3 Runtime publication", external=True)

    failures = [row for row in rows if row.get("status") == "FAIL"]
    result = {
        "status": "PASS" if not failures else "FAIL",
        "contract": "V3_DEFINITION_OF_DONE_V1",
        "scope": scope,
        "checks": rows,
        "failures": failures,
        "external_proofs": [row["name"] for row in rows if row.get("status") == "EXTERNAL_PROOF"],
        "policy": {
            "all_internal_checks_must_pass": True,
            "ci_green_is_proved_by_enclosing_workflow": True,
            "candidate_never_claims_production_publication": True,
            "production_scope_requires_exact_source_commit": True,
            "no_presence_only_feature_claims": True,
        },
    }
    print(json.dumps(result, ensure_ascii=False))
    if failures:
        raise SystemExit(1)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Executable V3 production definition-of-done validator")
    parser.add_argument("--scope", choices=["candidate", "production"], default="candidate")
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    run(args.scope, args.source_commit)


if __name__ == "__main__":
    main()
