from __future__ import annotations

import json
from time import perf_counter

from src.engines.v4_decision_pipeline import OUTFILE, run as run_decision_pipeline
from src.engines.v4_price_context import serve_price_evidence
from src.engines.v4_weather_tactical_overlay import apply_weather_overlay
from src.services.owned_challenger_decision_service import load_policy, run as run_owned_challenger_decision
from src.services.projected_value_market_challenger import augment_challenger, discover, rerank_visible_watchlist
from src.services.runtime_policy import decision_compute_slo_ms
from src.utils import DATA, atomic_json, read_json

DECISION_COMPUTE_SLO_MS = decision_compute_slo_ms()


def _load_price_context() -> dict:
    prices = read_json(DATA / "prices.json", {})
    if not prices.get("players"):
        raise RuntimeError("canonical Prediction-owned price context is required")
    all15 = prices.get("all15_actionable_price_radar") or []
    if len(all15) != 15:
        raise RuntimeError(f"price context requires exact ALL15 owned coverage, got {len(all15)}")
    return prices


def _watchlist_price_evidence(prices: dict, tactical: dict) -> list[dict]:
    watchlist_ids = [int(row.get("element") or 0) for row in tactical.get("watchlist") or []]
    all20 = serve_price_evidence(prices, watchlist_ids, owned=False, limit=20)
    if len(all20) != 20:
        raise RuntimeError(f"price context requires exact governed ALL20 watchlist coverage, got {len(all20)}")
    return all20


def run() -> dict:
    wall_started = perf_counter()
    runtime_context: dict = {}
    out = run_decision_pipeline(runtime_context=runtime_context)

    price_started = perf_counter()
    price_context = _load_price_context()
    price_context_ms = round((perf_counter() - price_started) * 1000.0, 2)

    discovery_started = perf_counter()
    predictions = runtime_context.get("predictions") or read_json(DATA / "predictions_v4.json", {})
    universe = runtime_context.get("universe") or read_json(DATA / "universe.json", {})
    team = read_json(DATA / "team.json", {})
    latest = read_json(DATA / "latest.json", {})
    raw_snapshot = read_json(DATA / "runtime" / "snapshot.v1.json", {})
    tactical_before = read_json(DATA / "tactical_serving_v4.json", {})
    policy = load_policy()
    discovery = discover(
        predictions=predictions,
        universe=universe,
        prices=price_context,
        raw_snapshot=raw_snapshot,
        team=team,
        policy=policy,
    )
    discovery_cfg = policy["projected_value_market_discovery"]
    tactical_reranked = rerank_visible_watchlist(
        tactical_before,
        discovery=discovery,
        predictions=predictions,
        universe=universe,
        per_position=int(discovery_cfg["visible_watchlist_per_position"]),
    )
    atomic_json(DATA / "tactical_serving_v4.json", tactical_reranked)
    all20 = _watchlist_price_evidence(price_context, tactical_reranked)
    discovery_ms = round((perf_counter() - discovery_started) * 1000.0, 2)

    weather_started = perf_counter()
    tactical = apply_weather_overlay(
        predictions=predictions,
        universe=universe,
    )
    weather_ms = round((perf_counter() - weather_started) * 1000.0, 2)

    challenger_started = perf_counter()
    challenger = run_owned_challenger_decision(canonical_arbitration=out.get("canonical_resolution"))
    challenger = augment_challenger(
        challenger,
        discovery=discovery,
        predictions=predictions,
        universe=universe,
        team=team,
        latest=latest,
        tactical=tactical,
        prices=price_context,
        policy=policy,
    )
    atomic_json(DATA / "owned_challenger_decision_v4.json", challenger)
    challenger_ms = round((perf_counter() - challenger_started) * 1000.0, 2)

    base_compute_ms = float((out.get("timings") or {}).get("total_pipeline_ms") or float("inf"))
    compute_ms = base_compute_ms + price_context_ms + discovery_ms + weather_ms + challenger_ms
    wall_ms = round((perf_counter() - wall_started) * 1000.0, 2)
    status = "PASS" if compute_ms < DECISION_COMPUTE_SLO_MS else "FAIL"

    out.setdefault("timings", {})["price_market_context_ms"] = price_context_ms
    out["timings"]["projected_value_market_discovery_ms"] = discovery_ms
    out["timings"]["weather_tactical_overlay_ms"] = weather_ms
    out["timings"]["owned_challenger_decision_ms"] = challenger_ms
    out["timings"]["total_pipeline_ms"] = round(compute_ms, 2)
    out["price_context"] = {
        "status": (price_context.get("health") or {}).get("status"),
        "source": price_context.get("source"),
        "contract": price_context.get("contract"),
        "all15_count": len(price_context.get("all15_actionable_price_radar") or []),
        "all20_count": len(all20),
        "all20_external_dss_watchlist": all20,
        "watchlist_source": "TACTICAL_SERVING_15_20_V1_AFTER_PROJECTED_VALUE_RERANK",
        "artifact_owner": "prediction",
        "optimization_access": "READ_ONLY_JOIN",
        "decision_chain_effect": "TIMING_AFFORDABILITY_OPTIONALITY_ONLY",
        "football_decision_authority": "SUBORDINATE",
    }
    out["projected_value_market_discovery"] = {
        "contract": discovery.get("contract"),
        "full_universe_scanned": discovery.get("full_universe_scanned"),
        "eligible_non_owned_count": discovery.get("eligible_non_owned_count"),
        "identity_pass_count": discovery.get("identity_pass_count"),
        "tainted_or_blocked_count": discovery.get("tainted_or_blocked_count"),
        "mandatory_candidate_count": len(discovery.get("mandatory_candidate_ids") or []),
        "mandatory_candidate_ids": discovery.get("mandatory_candidate_ids") or [],
        "visible_watchlist_reranked": True,
        "market_timing_is_not_football_authority": True,
        "mandatory_review_is_not_automatic_buy": True,
        "artifact": "data/owned_challenger_decision_v4.json",
    }
    out["weather_context"] = {
        **(tactical.get("weather_context") or {}),
        "decision_chain_effect": "UNCERTAINTY_AND_TACTICAL_ADVISORY_ONLY",
        "expected_xpts_mean_adjustment": 0.0,
    }
    discovery_artifact = challenger.get("projected_value_market_discovery") or {}
    out["owned_challenger_decision"] = {
        "status": challenger.get("status"),
        "contract": challenger.get("contract"),
        "owned_count": challenger.get("owned_count"),
        "governed_watchlist_count": challenger.get("governed_watchlist_count"),
        "comparison_count": challenger.get("comparison_count"),
        "main_transfer_battle_count": len(challenger.get("main_transfer_battles") or []),
        "multi_transfer_package_count": len(challenger.get("multi_transfer_packages") or []),
        "mandatory_candidate_count": len(discovery_artifact.get("mandatory_candidate_ids") or []),
        "mandatory_candidate_coverage_complete": discovery_artifact.get("mandatory_candidate_coverage_complete"),
        "challenge_signal": challenger.get("challenge_signal"),
        "overall_decision": challenger.get("overall_decision"),
        "decision_authority": challenger.get("decision_authority"),
        "execution_authorized": challenger.get("execution_authorized"),
        "artifact": "data/owned_challenger_decision_v4.json",
        "owner": "optimization",
    }
    out["performance_slo"] = {
        "scope": "deterministic_decision_compute_excludes_external_source_network_io",
        "limit_ms": DECISION_COMPUTE_SLO_MS,
        "actual_ms": round(compute_ms, 2),
        "service_wall_ms": wall_ms,
        "status": status,
    }
    out.setdefault("performance_guardrails", {})["decision_compute_hard_slo_lt_5s"] = True
    out["performance_guardrails"]["external_network_latency_reported_separately"] = True
    out["performance_guardrails"]["price_predictor_network_io_reuses_raw_snapshot"] = True
    out["performance_guardrails"]["price_artifact_prediction_single_writer"] = True
    out["performance_guardrails"]["optimization_price_access_read_only"] = True
    out["performance_guardrails"]["price_signal_cannot_authorize_football_action"] = True
    out["performance_guardrails"]["weather_network_io_occurs_in_enrichment_not_decision_compute"] = True
    out["performance_guardrails"]["weather_mean_xpts_mutation"] = False
    out["performance_guardrails"]["owned_challenger_runs_inside_optimization_owner"] = True
    out["performance_guardrails"]["owned_challenger_creates_no_second_decision_authority"] = True
    out["performance_guardrails"]["projected_value_market_full_universe_single_scan"] = True
    out["performance_guardrails"]["mandatory_market_review_is_not_execution_authority"] = True
    atomic_json(OUTFILE, out)
    print(json.dumps({
        "service": "optimization",
        "status": status,
        "decision_compute_ms": round(compute_ms, 2),
        "price_context_ms": price_context_ms,
        "projected_value_market_discovery_ms": discovery_ms,
        "price_context": (price_context.get("health") or {}).get("status"),
        "all15": len(price_context.get("all15_actionable_price_radar") or []),
        "all20": len(all20),
        "mandatory_challengers": len(discovery.get("mandatory_candidate_ids") or []),
        "mandatory_coverage": discovery_artifact.get("mandatory_candidate_coverage_complete"),
        "weather_overlay_ms": weather_ms,
        "weather_context": (tactical.get("weather_context") or {}).get("status"),
        "owned_challenger_ms": challenger_ms,
        "owned_challenger_status": challenger.get("status"),
        "owned_challenger_signal": challenger.get("challenge_signal"),
        "canonical_decision": challenger.get("overall_decision"),
        "limit_ms": DECISION_COMPUTE_SLO_MS,
    }, ensure_ascii=False))
    if status != "PASS":
        raise RuntimeError(f"decision compute SLO exceeded: {compute_ms:.1f}ms >= {DECISION_COMPUTE_SLO_MS:.0f}ms")
    return out


if __name__ == "__main__":
    run()