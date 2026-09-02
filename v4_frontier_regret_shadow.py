from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.engines.v4_wc_optimizer import build_candidates
from src.engines.v4_wc_package_audit import audit_packages_from_candidates
from src.utils import CONFIG, DATA, read_json
from v4_frontier_exclusion_audit import PRODUCTION_FRONTIER_PER_POSITION


SHADOW_CONFIG = CONFIG / "frontier_regret_shadow.json"
OUTPUT_PATH = DATA / "frontier_regret_shadow_v4.json"


def _ids(rows) -> list[int]:
    return [int(row.get("element")) for row in (rows or []) if row.get("element") is not None]


def _package_signature(package: dict | None):
    if not package:
        return None
    return {
        "replacements": int(package.get("replacements") or 0),
        "out": sorted(_ids(package.get("out"))),
        "in": sorted(_ids(package.get("in"))),
    }


def _compact_package(package: dict | None):
    if not package:
        return None
    return {
        "signature": _package_signature(package),
        "classification": package.get("classification"),
        "adjusted_best_xi_gain_5": float(package.get("adjusted_best_xi_gain_5") or 0.0),
        "adjusted_utility_gain_5": float(package.get("adjusted_utility_gain_5") or 0.0),
        "delta_best_xi_xpts_5": float(package.get("delta_best_xi_xpts_5") or 0.0),
        "delta_bench_adjusted_utility_5": float(package.get("delta_bench_adjusted_utility_5") or 0.0),
        "target_itb": int(package.get("target_itb") or 0),
    }


def _comparison(production: dict | None, challenger: dict | None, epsilon: float) -> dict:
    prod = _compact_package(production)
    chal = _compact_package(challenger)
    prod_u = float((prod or {}).get("adjusted_utility_gain_5") or 0.0)
    chal_u = float((chal or {}).get("adjusted_utility_gain_5") or 0.0)
    prod_xi = float((prod or {}).get("adjusted_best_xi_gain_5") or 0.0)
    chal_xi = float((chal or {}).get("adjusted_best_xi_gain_5") or 0.0)
    utility_regret = round(chal_u - prod_u, 4)
    xi_regret = round(chal_xi - prod_xi, 4)
    return {
        "production": prod,
        "challenger": chal,
        "package_changed": (prod or {}).get("signature") != (chal or {}).get("signature"),
        "utility_regret_vs_production": utility_regret,
        "xi_regret_vs_production": xi_regret,
        "regret_observed": utility_regret > epsilon or xi_regret > epsilon,
    }


def _validate_config(config: dict) -> tuple[list[int], int, int, int, int, float]:
    widths = [int(x) for x in (config.get("comparison_widths") or [])]
    if not widths:
        raise RuntimeError("frontier regret shadow comparison_widths is empty")
    if widths[0] != PRODUCTION_FRONTIER_PER_POSITION:
        raise RuntimeError(
            f"shadow baseline width {widths[0]} does not match production frontier "
            f"{PRODUCTION_FRONTIER_PER_POSITION}"
        )
    if widths != sorted(set(widths)):
        raise RuntimeError("frontier regret shadow widths must be unique and ascending")
    if any(width < PRODUCTION_FRONTIER_PER_POSITION for width in widths):
        raise RuntimeError("shadow widths may not be narrower than production")

    max_replacements = int(config.get("max_replacements") or 4)
    top_per_size = int(config.get("top_per_size") or 8)
    beam_size = int(config.get("beam_size") or 28)
    history_limit = int(config.get("history_limit") or 48)
    epsilon = float(config.get("regret_epsilon") or 0.01)
    if max_replacements < 1 or top_per_size < 1 or beam_size < 1 or history_limit < 1 or epsilon < 0:
        raise RuntimeError("invalid frontier regret shadow config")
    return widths, max_replacements, top_per_size, beam_size, history_limit, epsilon


def _artifact_frontier_width(production_artifact: dict) -> int | None:
    for parent in (production_artifact.get("performance") or {}, production_artifact.get("guardrails") or {}):
        value = parent.get("frontier_per_position")
        if value is not None:
            return int(value)
    return None


def _production_parity(production_artifact: dict, shadow_report: dict, epsilon: float) -> dict:
    if not production_artifact:
        return {"status": "UNAVAILABLE", "reason": "production artifact missing"}
    artifact_width = _artifact_frontier_width(production_artifact)
    if artifact_width is not None and artifact_width != PRODUCTION_FRONTIER_PER_POSITION:
        raise RuntimeError(
            f"production artifact frontier width {artifact_width} disagrees with canonical width "
            f"{PRODUCTION_FRONTIER_PER_POSITION}"
        )

    artifact_best = production_artifact.get("best_by_replacement_count") or {}
    shadow_best = shadow_report.get("best_by_replacement_count") or {}
    per_k = {}
    exact = True
    for k in range(1, int(shadow_report.get("max_replacements") or 4) + 1):
        key = str(k)
        left = artifact_best.get(key)
        right = shadow_best.get(key)
        same_signature = _package_signature(left) == _package_signature(right)
        utility_delta = round(
            float((right or {}).get("adjusted_utility_gain_5") or 0.0)
            - float((left or {}).get("adjusted_utility_gain_5") or 0.0),
            4,
        )
        xi_delta = round(
            float((right or {}).get("adjusted_best_xi_gain_5") or 0.0)
            - float((left or {}).get("adjusted_best_xi_gain_5") or 0.0),
            4,
        )
        matches = same_signature and abs(utility_delta) <= epsilon and abs(xi_delta) <= epsilon
        exact = exact and matches
        per_k[key] = {
            "signature_matches": same_signature,
            "utility_delta": utility_delta,
            "xi_delta": xi_delta,
            "matches": matches,
        }

    global_left = production_artifact.get("recommended_package")
    global_right = shadow_report.get("recommended_package")
    global_signature_matches = _package_signature(global_left) == _package_signature(global_right)
    exact = exact and global_signature_matches
    return {
        "status": "PASS" if exact else "FAIL",
        "artifact_frontier_per_position": artifact_width,
        "expected_frontier_per_position": PRODUCTION_FRONTIER_PER_POSITION,
        "per_replacement_count": per_k,
        "global_signature_matches": global_signature_matches,
        "exact_semantic_parity": exact,
    }


def frontier_regret_shadow_from_candidates(
    candidates,
    locked: dict,
    *,
    config: dict,
    production_artifact: dict | None = None,
    previous_output: dict | None = None,
    source_snapshot: dict | None = None,
) -> dict:
    widths, max_replacements, top_per_size, beam_size, history_limit, epsilon = _validate_config(config)

    reports = {}
    for width in widths:
        reports[width] = audit_packages_from_candidates(
            candidates,
            locked,
            max_replacements=max_replacements,
            budget=None,
            per_position_frontier=width,
            top_per_size=top_per_size,
            beam_size=beam_size,
        )

    production = reports[PRODUCTION_FRONTIER_PER_POSITION]
    by_width = {}
    any_per_k_regret = False
    any_global_regret = False
    any_package_change = False
    max_utility_regret = 0.0
    max_xi_regret = 0.0

    for width in widths:
        report = reports[width]
        per_k = {}
        for k in range(1, max_replacements + 1):
            key = str(k)
            cmp = _comparison(
                (production.get("best_by_replacement_count") or {}).get(key),
                (report.get("best_by_replacement_count") or {}).get(key),
                epsilon,
            )
            per_k[key] = cmp
            any_per_k_regret = any_per_k_regret or cmp["regret_observed"]
            any_package_change = any_package_change or cmp["package_changed"]
            max_utility_regret = max(max_utility_regret, cmp["utility_regret_vs_production"])
            max_xi_regret = max(max_xi_regret, cmp["xi_regret_vs_production"])

        global_cmp = _comparison(production.get("recommended_package"), report.get("recommended_package"), epsilon)
        any_global_regret = any_global_regret or global_cmp["regret_observed"]
        any_package_change = any_package_change or global_cmp["package_changed"]
        max_utility_regret = max(max_utility_regret, global_cmp["utility_regret_vs_production"])
        max_xi_regret = max(max_xi_regret, global_cmp["xi_regret_vs_production"])
        by_width[str(width)] = {
            "frontier_per_position": width,
            "screened_players": report.get("screened_players"),
            "frontier_players": report.get("frontier_players"),
            "evaluated_packages": (report.get("performance") or {}).get("evaluated_packages"),
            "overall_verdict": report.get("overall_verdict"),
            "per_replacement_count": per_k,
            "global_winner": global_cmp,
        }

    if any_global_regret:
        status = "GLOBAL_REGRET_OBSERVED"
    elif any_per_k_regret:
        status = "PER_K_REGRET_OBSERVED"
    else:
        status = "NO_REGRET_OBSERVED"

    parity = _production_parity(production_artifact or {}, production, epsilon)
    generated_at = datetime.now(timezone.utc).isoformat()
    observation = {
        "generated_at": generated_at,
        "source_snapshot": source_snapshot or {},
        "status": status,
        "production_frontier_per_position": PRODUCTION_FRONTIER_PER_POSITION,
        "comparison_widths": widths,
        "max_utility_regret": round(max_utility_regret, 4),
        "max_xi_regret": round(max_xi_regret, 4),
        "per_k_regret_observed": any_per_k_regret,
        "global_regret_observed": any_global_regret,
        "package_change_observed": any_package_change,
        "search_complete_claim_supported": not any_per_k_regret and not any_global_regret,
        "global_optimum_stable_across_scanned_widths": not any_global_regret,
        "production_parity_status": parity.get("status"),
    }

    history = list((previous_output or {}).get("history") or [])
    history.append(observation)
    history = history[-history_limit:]

    return {
        "schema_version": 1,
        "engine": "v4-frontier-regret-shadow",
        "audit_only": True,
        "decision_authority": "NONE",
        "affects_search": False,
        "affects_decision": False,
        "failure_cannot_block_core_publish": True,
        "production_frontier_unchanged": True,
        "production_frontier_per_position": PRODUCTION_FRONTIER_PER_POSITION,
        "comparison_widths": widths,
        "regret_epsilon": epsilon,
        "status": status,
        "interpretation": {
            "per_k_regret_observed": any_per_k_regret,
            "global_regret_observed": any_global_regret,
            "package_change_observed": any_package_change,
            "max_utility_regret": round(max_utility_regret, 4),
            "max_xi_regret": round(max_xi_regret, 4),
            "search_complete_claim_supported": not any_per_k_regret and not any_global_regret,
            "global_optimum_stable_across_scanned_widths": not any_global_regret,
            "evidence_scope": "observational comparison across configured widths only; not proof of exhaustive global optimality",
        },
        "production_parity": parity,
        "by_width": by_width,
        "current_observation": observation,
        "history": history,
        "history_limit": history_limit,
        "guardrails": {
            "production_width_is_baseline": True,
            "production_search_width_unchanged": True,
            "production_ranking_semantics_unchanged": True,
            "production_beam_semantics_unchanged": True,
            "shadow_has_zero_decision_authority": True,
            "shadow_failure_is_non_blocking": True,
        },
    }


def audit_current_runtime() -> dict:
    config = read_json(SHADOW_CONFIG, {})
    if config.get("enabled") is not True:
        raise RuntimeError("frontier regret shadow is disabled")
    predictions = read_json(DATA / "predictions_v4.json", {})
    universe = read_json(DATA / "universe.json", {})
    locked = read_json(CONFIG / "locked_squad.json", {})
    production_artifact = read_json(DATA / "owned_challenger_decision_v4.json", {})
    previous_output = read_json(OUTPUT_PATH, {})
    latest = read_json(DATA / "latest.json", {})
    candidates = build_candidates(predictions, universe)
    source_snapshot = {
        "predictions_generated_at": predictions.get("generated_at"),
        "latest_generated_at": latest.get("generated_at"),
        "runtime_publish_at": latest.get("runtime_publish_at"),
    }
    return frontier_regret_shadow_from_candidates(
        candidates,
        locked,
        config=config,
        production_artifact=production_artifact,
        previous_output=previous_output,
        source_snapshot=source_snapshot,
    )


def run() -> dict:
    out = audit_current_runtime()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": out["status"],
        "max_utility_regret": out["interpretation"]["max_utility_regret"],
        "max_xi_regret": out["interpretation"]["max_xi_regret"],
        "global_regret_observed": out["interpretation"]["global_regret_observed"],
        "production_parity": out["production_parity"].get("status"),
    }, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
