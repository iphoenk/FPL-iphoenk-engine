from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


GENERATED_TO_CLEAR = (
    "data/decision_hot_cache_v4.json",
    "data/wc_decision_v4.json",
    "data/wc_package_audit_v4.json",
    "data/lineup_decision_v4.json",
    "data/recommendation_sanity_v4.json",
    "data/tactical_serving_v4.json",
    "data/decision_arbitration_v4.json",
    "data/decision_pipeline_v4.json",
    "data/effective_plan_v4.json",
    "data/gw_scorecard_v4.json",
    "data/framework_health_v4.json",
    "data/checkpoint_decision_v4.json",
    "data/serving_payload_v4.json",
    "data/serving_benchmark_v4.json",
)

CHAIN = (
    "src.services.validation_service",
    "src.services.optimization_slo_service",
    "src.services.user_decision_overlay_service",
    "src.services.gw_scorecard_service",
    "src.services.governance_service",
)


def load(root: Path, rel: str) -> dict:
    path = root / rel
    if not path.is_file():
        raise RuntimeError(f"required parity artifact missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"parity artifact must be object: {path}")
    return payload


def ids(rows: Any) -> list[int]:
    return [int(row.get("element") or 0) for row in (rows or [])]


def nested(payload: dict, *path: str) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def named_fields(payload: Any, token: str, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else key
            if token in key.lower():
                out[path] = value
            out.update(named_fields(value, token, path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            out.update(named_fields(value, token, f"{prefix}[{index}]"))
    return out


def clear_generated(root: Path) -> None:
    for rel in GENERATED_TO_CLEAR:
        path = root / rel
        if path.exists():
            path.unlink()


def run_chain(root: Path) -> list[dict]:
    clear_generated(root)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    results = []
    for module in CHAIN:
        proc = subprocess.run(
            [sys.executable, "-m", module],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        results.append({
            "module": module,
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        })
        if proc.returncode != 0:
            raise RuntimeError(
                f"{root.name}: {module} failed rc={proc.returncode}\n"
                f"stdout:\n{proc.stdout[-4000:]}\n"
                f"stderr:\n{proc.stderr[-4000:]}"
            )
    return results


def semantic_projection(root: Path) -> dict:
    wc = load(root, "data/wc_decision_v4.json")
    package = load(root, "data/wc_package_audit_v4.json")
    sanity = load(root, "data/recommendation_sanity_v4.json")
    lineup = load(root, "data/lineup_decision_v4.json")
    tactical = load(root, "data/tactical_serving_v4.json")
    arbitration = load(root, "data/decision_arbitration_v4.json")
    pipeline = load(root, "data/decision_pipeline_v4.json")
    effective = load(root, "data/effective_plan_v4.json")
    scorecard = load(root, "data/gw_scorecard_v4.json")
    health = load(root, "data/framework_health_v4.json")
    checkpoint = load(root, "data/checkpoint_decision_v4.json")
    serving = load(root, "data/serving_payload_v4.json")

    bench = lineup.get("bench") or {}
    effective_plan = effective.get("effective_plan") or {}
    effective_bench = effective_plan.get("bench") or {}
    transfer = nested(arbitration, "dimensions", "transfer") or {}

    return {
        "squad_decision": {
            "wc_classification": wc.get("classification"),
            "optimized_elements": wc.get("optimized_elements"),
            "package_verdict": package.get("overall_verdict"),
            "recommended_package": package.get("recommended_package"),
            "sanity_verdict": sanity.get("final_verdict"),
            "sanity_recommended_package": sanity.get("recommended_package"),
            "arbitration_squad": nested(arbitration, "dimensions", "squad"),
        },
        "transfer_decision": {
            "action": transfer.get("action"),
            "candidate_state": transfer.get("candidate_state"),
            "out": transfer.get("out"),
            "in": transfer.get("in"),
            "replacements": transfer.get("replacements"),
            "blocking_reasons": transfer.get("blocking_reasons"),
            "execution_authorized": transfer.get("execution_authorized"),
            "multi_horizon_projection": transfer.get("multi_horizon_projection"),
            "hit_fields": {
                **named_fields(package.get("recommended_package") or {}, "hit"),
                **named_fields(sanity.get("recommended_package") or {}, "hit"),
                **named_fields(transfer, "hit"),
            },
        },
        "lineup": {
            "formation": lineup.get("formation"),
            "formation_state": lineup.get("formation_state"),
            "starting_xi": ids(lineup.get("starting_xi")),
            "bench_gk": int((bench.get("gk") or {}).get("element") or 0),
            "bench_order": ids(bench.get("order")),
            "captain": int((lineup.get("captain") or {}).get("element") or 0),
            "vice_captain": int((lineup.get("vice_captain") or {}).get("element") or 0),
            "chip": nested(lineup, "chip_context", "active_chip"),
            "gk_selection": lineup.get("gk_selection"),
            "bench_governance": lineup.get("bench_governance"),
            "captaincy_governance": lineup.get("captaincy_governance"),
            "governance": lineup.get("governance"),
        },
        "tactical": {
            "owned_15": tactical.get("owned"),
            "watchlist_20": tactical.get("watchlist"),
            "counts": tactical.get("counts"),
            "guardrails": tactical.get("guardrails"),
        },
        "canonical_resolution": {
            "resolution_id": arbitration.get("resolution_id"),
            "overall_action": arbitration.get("overall_action"),
            "headline": arbitration.get("headline"),
            "source_verdict": arbitration.get("source_verdict"),
            "dimensions": arbitration.get("dimensions"),
            "guardrails": arbitration.get("guardrails"),
        },
        "decision_pipeline": {
            "decision_authority": pipeline.get("decision_authority"),
            "planning_squad": pipeline.get("planning_squad"),
            "results": pipeline.get("results"),
            "performance_guardrails": {
                "search_quality_reduction": nested(pipeline, "performance_guardrails", "search_quality_reduction"),
                "planning_squad_from_team_contract": nested(pipeline, "performance_guardrails", "planning_squad_from_team_contract"),
                "stale_lock_players_not_direct_optimizer_input": nested(pipeline, "performance_guardrails", "stale_lock_players_not_direct_optimizer_input"),
                "engine_lineup_is_advisory_only": nested(pipeline, "performance_guardrails", "engine_lineup_is_advisory_only"),
                "manual_override_applied_in_separate_microservice": nested(pipeline, "performance_guardrails", "manual_override_applied_in_separate_microservice"),
            },
        },
        "effective_plan": {
            "status": effective.get("status"),
            "planning_gw": effective.get("planning_gw"),
            "team_authority": effective.get("team_authority"),
            "canonical_resolution": effective.get("canonical_resolution"),
            "user_override": effective.get("user_override"),
            "formation": effective_plan.get("formation"),
            "starting_xi": ids(effective_plan.get("starting_xi")),
            "bench_gk": int((effective_bench.get("gk") or {}).get("element") or 0),
            "bench_order": ids(effective_bench.get("order")),
            "captain": int((effective_plan.get("captain") or {}).get("element") or 0),
            "vice_captain": int((effective_plan.get("vice_captain") or {}).get("element") or 0),
            "chip": nested(effective_plan, "chip_context", "active_chip"),
            "comparison": effective.get("comparison"),
            "guardrails": effective.get("guardrails"),
        },
        "scorecard": {
            "status": scorecard.get("status"),
            "phase": scorecard.get("phase"),
            "previous_gw": scorecard.get("previous_gw"),
            "planning_gw": scorecard.get("planning_gw"),
            "guardrails": scorecard.get("guardrails"),
        },
        "legality": {
            "gate0_pass": nested(health, "gate0", "pass"),
            "engine_plan": nested(health, "gate0", "plan_authority_validation", "engine_plan"),
            "effective_plan": nested(health, "gate0", "plan_authority_validation", "effective_plan"),
            "effective_plan_legality_enforced": nested(health, "governance", "effective_plan_legality_enforced"),
            "engine_and_effective_plan_legality_reported_separately": nested(health, "governance", "engine_and_effective_plan_legality_reported_separately"),
        },
        "report": {
            "action_state": checkpoint.get("action_state"),
            "headline": checkpoint.get("headline"),
            "human_decision": nested(checkpoint, "human_report", "decision"),
            "human_summary": nested(checkpoint, "human_report", "summary"),
            "squad": checkpoint.get("squad"),
            "decision": checkpoint.get("decision"),
            "lineup": checkpoint.get("lineup"),
            "readiness": checkpoint.get("readiness"),
        },
        "serving": {
            "canonical_resolution_id": serving.get("canonical_resolution_id"),
            "owned_15": serving.get("owned_15"),
            "watchlist_20": serving.get("watchlist_20"),
            "xi": serving.get("xi"),
            "bench": serving.get("bench"),
            "captain": serving.get("captain"),
            "vice_captain": serving.get("vice_captain"),
            "guardrails": serving.get("guardrails"),
        },
        "search_width": {
            "package_frontier": nested(package, "performance", "frontier_per_position"),
            "package_beam": nested(package, "performance", "beam_size"),
            "package_evaluated": nested(package, "performance", "evaluated_packages"),
            "package_search_quality_reduction": nested(package, "performance", "search_quality_reduction"),
            "package_guardrail_search_width_unchanged": nested(package, "guardrails", "search_width_unchanged"),
        },
    }


def digest(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-root", required=True)
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    base_root = Path(args.base_root).resolve()
    candidate_root = Path(args.candidate_root).resolve()
    base_runs = run_chain(base_root)
    candidate_runs = run_chain(candidate_root)
    base = semantic_projection(base_root)
    candidate = semantic_projection(candidate_root)
    equal = base == candidate
    out = {
        "schema_version": 1,
        "base_root": str(base_root),
        "candidate_root": str(candidate_root),
        "exact_semantic_parity": equal,
        "base_sha256": digest(base),
        "candidate_sha256": digest(candidate),
        "base_chain": base_runs,
        "candidate_chain": candidate_runs,
        "projection": candidate if equal else None,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "exact_semantic_parity": equal,
        "base_sha256": out["base_sha256"],
        "candidate_sha256": out["candidate_sha256"],
        "owned": len(candidate["tactical"]["owned_15"] or []),
        "watchlist": len(candidate["tactical"]["watchlist_20"] or []),
        "xi": len(candidate["lineup"]["starting_xi"] or []),
        "package_evaluated": candidate["search_width"]["package_evaluated"],
        "beam": candidate["search_width"]["package_beam"],
        "frontier": candidate["search_width"]["package_frontier"],
    }, ensure_ascii=False))
    if not equal:
        import difflib
        before = json.dumps(base, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
        after = json.dumps(candidate, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
        diff = "\n".join(difflib.unified_diff(before, after, fromfile="canonical", tofile="candidate", lineterm=""))
        print(diff[:20000])
        raise SystemExit("exact end-to-end decision parity failed")


if __name__ == "__main__":
    main()
