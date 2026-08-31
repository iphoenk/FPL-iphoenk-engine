from __future__ import annotations

import json
from time import perf_counter

from src.engines.v4_decision_pipeline import OUTFILE, run as run_decision_pipeline
from src.engines.v4_price_context import serve_price_evidence
from src.engines.v4_weather_tactical_overlay import apply_weather_overlay
from src.services.owned_challenger_decision_service import run as run_owned_challenger_decision
from src.utils import DATA, atomic_json, read_json

DECISION_COMPUTE_SLO_MS = 5000.0


def _load_price_context() -> tuple[dict, list[dict]]:
    prices = read_json(DATA / "prices.json", {})
    tactical = read_json(DATA / "tactical_serving_v4.json", {})
    if not prices.get("players"):
        raise RuntimeError("canonical Prediction-owned price context is required")
    all15 = prices.get("all15_actionable_price_radar") or []
    if len(all15) != 15:
        raise RuntimeError(f"price context requires exact ALL15 owned coverage, got {len(all15)}")
    watchlist_ids = [int(row.get("element") or 0) for row in tactical.get("watchlist") or []]
    all20 = serve_price_evidence(prices, watchlist_ids, owned=False, limit=20)
    if len(all20) != 20:
        raise RuntimeError(f"price context requires exact governed ALL20 watchlist coverage, got {len(all20)}")
    return prices, all20


def run() -> dict:
    wall_started = perf_counter()
    runtime_context: dict = {}
    out = run_decision_pipeline(runtime_context=runtime_context)

    price_started = perf_counter()
    price_context, all20 = _load_price_context()
    price_context_ms = round((perf_counter() - price_started) * 1000.0, 2)

    weather_started = perf_counter()
    tactical = apply_weather_overlay(
        predictions=runtime_context.get("predictions"),
        universe=runtime_context.get("universe"),
    )
    weather_ms = round((perf_counter() - weather_started) * 1000.0, 2)

    challenger_started = perf_counter()
    challenger = run_owned_challenger_decision(canonical_arbitration=out.get("canonical_resolution"))
    challenger_ms = round((perf_counter() - challenger_started) * 1000.0, 2)

    base_compute_ms = float((out.get("timings") or {}).get("total_pipeline_ms") or float("inf"))
    compute_ms = base_compute_ms + price_context_ms + weather_ms + challenger_ms
    wall_ms = round((perf_counter() - wall_started) * 1000.0, 2)
    status = "PASS" if compute_ms < DECISION_COMPUTE_SLO_MS else "FAIL"

    out.setdefault("timings", {})["price_market_context_ms"] = price_context_ms
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
        "watchlist_source": "TACTICAL_SERVING_15_20_V1",
        "artifact_owner": "prediction",
        "optimization_access": "READ_ONLY_JOIN",
        "decision_chain_effect": "TIMING_AFFORDABILITY_OPTIONALITY_ONLY",
        "football_decision_authority": "SUBORDINATE",
    }
    out["weather_context"] = {
        **(tactical.get("weather_context") or {}),
        "decision_chain_effect": "UNCERTAINTY_AND_TACTICAL_ADVISORY_ONLY",
        "expected_xpts_mean_adjustment": 0.0,
    }
    out["owned_challenger_decision"] = {
        "status": challenger.get("status"),
        "contract": challenger.get("contract"),
        "owned_count": challenger.get("owned_count"),
        "governed_watchlist_count": challenger.get("governed_watchlist_count"),
        "comparison_count": challenger.get("comparison_count"),
        "main_transfer_battle_count": len(challenger.get("main_transfer_battles") or []),
        "multi_transfer_package_count": len(challenger.get("multi_transfer_packages") or []),
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
    atomic_json(OUTFILE, out)
    print(json.dumps({
        "service": "optimization",
        "status": status,
        "decision_compute_ms": round(compute_ms, 2),
        "price_context_ms": price_context_ms,
        "price_context": (price_context.get("health") or {}).get("status"),
        "all15": len(price_context.get("all15_actionable_price_radar") or []),
        "all20": len(all20),
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
