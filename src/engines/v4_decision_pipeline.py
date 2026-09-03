from __future__ import annotations

import hashlib
import json
import traceback
from multiprocessing import get_context
from pathlib import Path
from time import perf_counter

from src.engines.v4_decision_arbitration import OUTFILE as ARBITRATION_OUTFILE, resolve_decision
from src.engines.v4_full_universe_package_search import search_full_universe_packages
from src.engines.v4_lineup_optimizer import optimize_lineup
from src.engines.v4_recommendation_sanity import sanity_report
from src.engines.v4_tactical_interaction import build_tactical_interactions
from src.engines.v4_tactical_serving import build_tactical_serving
from src.engines.v4_wc_optimizer import build_candidates
from src.engines.v4_wc_optimizer_fast import decision_report_from_candidates_fast
from src.services.contracts import file_digest
from src.utils import CONFIG, DATA, atomic_json, read_json

OUTFILE = DATA / "decision_pipeline_v4.json"
TACTICAL_OUTFILE = DATA / "tactical_serving_v4.json"
TACTICAL_INTERACTION_OUTFILE = DATA / "tactical_interaction_v4.json"
UNDERSTAT_FILE = DATA / "understat_tactical_v4.json"
DECISION_CACHE = DATA / "decision_hot_cache_v4.json"
WC_OUTFILE = DATA / "wc_decision_v4.json"
PACKAGE_OUTFILE = DATA / "wc_package_audit_v4.json"
LINEUP_OUTFILE = DATA / "lineup_decision_v4.json"
CACHE_ALGORITHM = "v4.9.7-full-universe-package-cache-v1-tactical-interaction"
_SHARED = None


def effective_planning_squad(team: dict, configured_lock: dict, latest: dict) -> dict:
    squad = list(team.get("squad") or [])
    ledger = {int(row.get("element") or 0): row for row in team.get("team_value_ledger") or []}
    if len(squad) != 15:
        raise RuntimeError(f"effective team contract must contain 15 players, got {len(squad)}")
    players = []
    for row in squad:
        element = int(row.get("element") or 0)
        value = ledger.get(element) or {}
        purchase_cost = value.get("purchase_cost", row.get("purchase_cost"))
        sell_cost_value = value.get("sell_cost")
        if sell_cost_value is None and purchase_cost is None:
            raise RuntimeError(f"effective owned player {element} lacks price evidence")
        players.append({
            "element": element,
            "name": row.get("name") or value.get("name"),
            "position": row.get("position") or value.get("position"),
            "purchase_cost": purchase_cost,
            "sell_cost": sell_cost_value,
        })
    planning_gw = int((latest.get("phase") or {}).get("planning_gw") or 0) or None
    target_raw = configured_lock.get("target_gw")
    target_gw = int(target_raw) if target_raw is not None else None
    authority = str(team.get("squad_authority") or "")
    targeted_override = authority in {"LOCKED_PRE_DEADLINE", "USER_CAPTURE_PREDEADLINE"} and target_gw == planning_gw
    wildcard_for_planning = bool(configured_lock.get("wildcard_active")) and targeted_override
    free_hit_for_planning = bool(configured_lock.get("free_hit_active")) and targeted_override
    free_transfers = int(configured_lock.get("free_transfers") or 0) if targeted_override else int(team.get("free_transfers") or 0)
    return {
        "players": players,
        "itb_tenths": int((team.get("totals") or {}).get("itb") or 0),
        "wildcard_active": wildcard_for_planning,
        "free_hit_active": free_hit_for_planning,
        "free_transfers": max(0, free_transfers),
        "transfer_cost_points": int(configured_lock.get("transfer_cost_points") or 0) if targeted_override else 0,
        "planning_override_active": targeted_override,
        "target_gw": target_gw if targeted_override else None,
        "authority_source": configured_lock.get("authority_source") if targeted_override else "OFFICIAL_FPL_PICKS",
        "squad_authority": authority,
        "baseline_gw": ((latest.get("phase") or {}).get("submitted_gw")),
        "planning_gw": planning_gw,
    }


def _decision_worker(kind, conn):
    t = perf_counter()
    try:
        shared = _SHARED
        if not shared:
            raise RuntimeError("decision worker started without shared inputs")
        if kind == "wc":
            out = decision_report_from_candidates_fast(shared["candidates"], shared["locked"])
            out["engine"] = "v4.9.2-wc-optimizer-truthful-health-exact-streaming"
            # This is still a full-squad/Wildcard search and must not be confused
            # with the transfer-package full-universe proof introduced in v4.9.7.
            out.setdefault("search_governance", {}).update({
                "search_type": "FULL_SQUAD_OPTIMIZATION",
                "global_optimality_guaranteed": False,
                "state": "RESTRICTED_BEAM_FULL_SQUAD",
            })
            atomic_json(WC_OUTFILE, out)
        elif kind == "packages":
            out = search_full_universe_packages(
                shared["candidates"],
                shared["locked"],
                predictions=shared["predictions"],
                universe=shared["universe"],
                understat=shared["understat_tactical"],
                interactions=shared["tactical_interactions"],
                prices=shared["prices"],
                max_replacements=3,
            )
            atomic_json(PACKAGE_OUTFILE, out)
        elif kind == "lineup":
            out = optimize_lineup(
                shared["predictions"], shared["universe"], shared["locked"],
                manual=None, tactical=shared["understat_tactical"],
            )
            atomic_json(LINEUP_OUTFILE, out)
        else:
            raise RuntimeError(f"unknown decision worker: {kind}")
        conn.send({"ok": True, "ms": round((perf_counter() - t) * 1000.0, 1)})
    except Exception:
        conn.send({"ok": False, "ms": round((perf_counter() - t) * 1000.0, 1), "error": traceback.format_exc()})
    finally:
        conn.close()


def _run_parallel_decisions(candidates, locked, predictions, universe, understat_tactical, tactical_interactions, prices):
    global _SHARED
    _SHARED = {
        "candidates": candidates,
        "locked": locked,
        "predictions": predictions,
        "universe": universe,
        "understat_tactical": understat_tactical,
        "tactical_interactions": tactical_interactions,
        "prices": prices,
    }
    ctx = get_context("fork")
    workers = {}
    wall = perf_counter()
    for kind, name in (("wc", "v497-wc-fast"), ("packages", "v497-packages-full-universe"), ("lineup", "v497-lineup")):
        recv, send = ctx.Pipe(duplex=False)
        process = ctx.Process(target=_decision_worker, args=(kind, send), name=name)
        process.start()
        send.close()
        workers[kind] = (recv, process)
    statuses = {}
    for kind, (recv, process) in workers.items():
        statuses[kind] = recv.recv()
        process.join()
        if not statuses[kind].get("ok") or process.exitcode != 0:
            raise RuntimeError(f"parallel {kind} worker failed:\n" + str(statuses[kind].get("error") or process.exitcode))
    wall_ms = round((perf_counter() - wall) * 1000.0, 1)
    _SHARED = None
    return statuses, wall_ms


def _candidate_semantics(candidates) -> list[dict]:
    return [
        {
            "element": row.element,
            "name": row.name,
            "position": row.position,
            "team_id": row.team_id,
            "team": row.team,
            "cost": row.cost,
            "x3": row.x3,
            "x5": row.x5,
            "x10": row.x10,
            "x15": row.x15,
            "uncertainty": row.uncertainty,
            "objective": row.objective,
            "gw_xpts": list(row.gw_xpts),
        }
        for row in sorted(candidates, key=lambda item: item.element)
    ]


def _understat_lineup_semantics(understat_tactical: dict, element: int) -> dict:
    row = ((understat_tactical.get("tactical_matchups") or {}).get(str(element)) or {})
    return {
        "state": row.get("state") or "INSUFFICIENT_EVIDENCE",
        "confidence": row.get("confidence"),
        "dimensions": row.get("dimensions") or {},
        "supporting_signals": row.get("supporting_signals") or [],
        "conflicting_signals": row.get("conflicting_signals") or [],
    }


def _lineup_semantics(predictions: dict, universe: dict, locked: dict, understat_tactical: dict) -> list[dict]:
    pmap = {int(row.get("element") or 0): row for row in predictions.get("players") or [] if row.get("element") is not None}
    umap = {int(row.get("element") or 0): row for row in universe.get("players") or [] if row.get("element") is not None}
    rows = []
    for owned in sorted(locked.get("players") or [], key=lambda row: int(row.get("element") or 0)):
        element = int(owned.get("element") or 0)
        pred = pmap.get(element) or {}
        uni = umap.get(element) or {}
        fixture = ((pred.get("fixtures") or [{}])[0]) or {}
        xmins = fixture.get("xmins") or {}
        rows.append({
            "element": element,
            "name": uni.get("name") or pred.get("name"),
            "position": uni.get("position") or pred.get("position"),
            "team": uni.get("team") or pred.get("team"),
            "xpts": fixture.get("xpts"),
            "lower80": fixture.get("lower80"),
            "upper80": fixture.get("upper80"),
            "start_probability": xmins.get("start_probability"),
            "start_probability_confidence": xmins.get("start_probability_confidence"),
            "bench_probability": xmins.get("bench_probability"),
            "dnp_probability": xmins.get("dnp_probability"),
            "tactical_role": (pred.get("priors") or {}).get("tactical_role"),
            "understat_close_call": _understat_lineup_semantics(understat_tactical, element),
        })
    return rows


def _package_tactical_semantics(interactions: dict) -> dict:
    return {
        "contract": interactions.get("contract"),
        "health": interactions.get("health") or {},
        "players": {
            str(element): {
                "confidence_dimensions": row.get("confidence_dimensions") or {},
                "tactical_interaction": row.get("tactical_interaction") or {},
                "roster_change": row.get("roster_change") or {},
                "formation": row.get("formation") or {},
            }
            for element, row in sorted(((interactions.get("players") or {}).items()), key=lambda item: int(item[0]))
        },
    }


def _price_semantics(prices: dict) -> dict:
    return {
        "contract": prices.get("contract") or {},
        "players": [
            {
                "element": row.get("element_id") or row.get("element"),
                "current_price": row.get("current_price"),
                "direction": row.get("direction") or row.get("risk_direction"),
                "urgency": row.get("model_urgency") or row.get("urgency"),
                "predictor_serving_state": row.get("predictor_serving_state"),
                "official_projections": row.get("official_projections") or [],
            }
            for row in sorted(prices.get("players") or [], key=lambda item: int(item.get("element_id") or item.get("element") or 0))
        ],
    }


def _semantic_fingerprint(
    predictions: dict,
    universe: dict,
    locked: dict,
    understat_tactical: dict | None = None,
    candidates=None,
    tactical_interactions: dict | None = None,
    prices: dict | None = None,
) -> str:
    normalized_candidates = candidates if candidates is not None else build_candidates(predictions, universe)
    serving_policy = read_json(CONFIG / "serving_improvement_registry.json", {}) or {}
    understat_policy = read_json(CONFIG / "intelligence" / "understat_tactical.json", {}) or {}
    full_search_policy = read_json(CONFIG / "intelligence" / "full_universe_package_search.json", {}) or {}
    tactical = understat_tactical or {}
    payload = {
        "algorithm": CACHE_ALGORITHM,
        "prediction_model": predictions.get("model_version"),
        "candidate_semantics": _candidate_semantics(normalized_candidates),
        "lineup_semantics": _lineup_semantics(predictions, universe, locked, tactical),
        "planning_squad": locked,
        "lineup_policy": serving_policy.get("lineup") or {},
        "understat_close_call_policy": understat_policy.get("close_call") or {},
        "full_universe_search_policy": full_search_policy,
        "package_tactical_semantics": _package_tactical_semantics(tactical_interactions or {}),
        "price_scenario_semantics": _price_semantics(prices or {}),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _cache_artifacts() -> dict[str, Path]:
    return {"wc": WC_OUTFILE, "packages": PACKAGE_OUTFILE, "lineup": LINEUP_OUTFILE}


def _cache_hit(fingerprint: str) -> tuple[bool, str]:
    cache = read_json(DECISION_CACHE, {})
    if cache.get("algorithm") != CACHE_ALGORITHM or cache.get("fingerprint") != fingerprint:
        return False, "FINGERPRINT_MISS"
    stored = cache.get("artifact_sha256") or {}
    for key, path in _cache_artifacts().items():
        try:
            current = file_digest(path)
        except Exception:
            return False, f"ARTIFACT_MISSING_{key.upper()}"
        if current != stored.get(key):
            return False, f"ARTIFACT_DIGEST_MISMATCH_{key.upper()}"
    return True, "EXACT_SEMANTIC_MATCH"


def _write_cache(fingerprint: str) -> None:
    atomic_json(DECISION_CACHE, {
        "schema_version": 3,
        "algorithm": CACHE_ALGORITHM,
        "fingerprint": fingerprint,
        "artifact_sha256": {key: file_digest(path) for key, path in _cache_artifacts().items()},
        "guardrails": {
            "exact_semantic_inputs_only": True,
            "bounded_consumer_projection_not_full_payload": True,
            "runtime_timestamps_not_consumed_by_cache_key": True,
            "understat_close_call_semantics_in_cache_key": True,
            "full_universe_package_policy_in_cache_key": True,
            "tactical_interaction_semantics_in_cache_key": True,
            "price_scenario_semantics_in_cache_key": True,
            "artifact_digest_verified_before_reuse": True,
            "manual_user_override_not_cached": True,
            "sanity_tactical_arbitration_rerun_every_time": True,
            "package_search_width_is_not_silently_bounded": True,
        },
    })


def run(*, runtime_context: dict | None = None):
    t0 = perf_counter()
    predictions = read_json(DATA / "predictions_v4.json", {})
    universe = read_json(DATA / "universe.json", {})
    configured_lock = read_json(CONFIG / "locked_squad.json", {})
    team = read_json(DATA / "team.json", {})
    latest = read_json(DATA / "latest.json", {})
    understat_tactical = read_json(UNDERSTAT_FILE, {})
    prices = read_json(DATA / "prices.json", {})
    locked = effective_planning_squad(team, configured_lock, latest)
    load_ms = round((perf_counter() - t0) * 1000.0, 1)

    t = perf_counter()
    candidates = build_candidates(predictions, universe)
    candidates_ms = round((perf_counter() - t) * 1000.0, 1)

    t = perf_counter()
    tactical_interactions = build_tactical_interactions(predictions, universe, understat_tactical)
    atomic_json(TACTICAL_INTERACTION_OUTFILE, tactical_interactions)
    tactical_interaction_ms = round((perf_counter() - t) * 1000.0, 1)

    t = perf_counter()
    fingerprint = _semantic_fingerprint(
        predictions,
        universe,
        locked,
        understat_tactical,
        candidates=candidates,
        tactical_interactions=tactical_interactions,
        prices=prices,
    )
    fingerprint_ms = round((perf_counter() - t) * 1000.0, 1)
    timings = {
        "load_shared_inputs_ms": load_ms,
        "build_candidates_ms": candidates_ms,
        "tactical_interaction_ms": tactical_interaction_ms,
        "semantic_fingerprint_ms": fingerprint_ms,
        "load_shared_inputs_candidates_and_fingerprint_ms": round(load_ms + candidates_ms + tactical_interaction_ms + fingerprint_ms, 1),
    }

    hit, cache_reason = _cache_hit(fingerprint)
    if hit:
        statuses = {
            "wc": {"ok": True, "ms": 0.0, "cache": True},
            "packages": {"ok": True, "ms": 0.0, "cache": True},
            "lineup": {"ok": True, "ms": 0.0, "cache": True},
        }
        parallel_wall = 0.0
    else:
        statuses, parallel_wall = _run_parallel_decisions(
            candidates, locked, predictions, universe, understat_tactical, tactical_interactions, prices,
        )
        _write_cache(fingerprint)

    timings.update({
        "optimizer_exact_cache_hit": hit,
        "optimizer_exact_cache_reason": cache_reason,
        "wc_decision_cpu_ms": statuses["wc"]["ms"],
        "package_audit_cpu_ms": statuses["packages"]["ms"],
        "lineup_cpu_ms": statuses["lineup"]["ms"],
        "decision_parallel_wall_ms": parallel_wall,
        "parallel_speedup_estimate": (
            0.0 if hit else round(
                (statuses["wc"]["ms"] + statuses["packages"]["ms"] + statuses["lineup"]["ms"]) / max(1.0, parallel_wall),
                3,
            )
        ),
    })

    wc = read_json(WC_OUTFILE, {})
    packages = read_json(PACKAGE_OUTFILE, {})
    lineup = read_json(LINEUP_OUTFILE, {})

    t = perf_counter()
    sanity = sanity_report(predictions, universe, packages, latest)
    atomic_json(DATA / "recommendation_sanity_v4.json", sanity)
    timings["evidence_sanity_ms"] = round((perf_counter() - t) * 1000.0, 1)

    t = perf_counter()
    previous_tactical = read_json(TACTICAL_OUTFILE, {})
    tactical = build_tactical_serving(
        predictions, universe, team, previous=previous_tactical,
        understat_data=understat_tactical,
    )
    atomic_json(TACTICAL_OUTFILE, tactical)
    timings["tactical_serving_ms"] = round((perf_counter() - t) * 1000.0, 1)

    t = perf_counter()
    arbitration = resolve_decision(sanity, lineup, latest, team, prices, tactical, predictions)
    atomic_json(ARBITRATION_OUTFILE, arbitration)
    timings["decision_arbitration_ms"] = round((perf_counter() - t) * 1000.0, 1)
    timings["total_pipeline_ms"] = round((perf_counter() - t0) * 1000.0, 1)

    search = packages.get("search") or {}
    out = {
        "schema_version": 4970,
        "engine": "v4.9.7-full-universe-package-tactical-interaction",
        "checkpoint_context": latest.get("checkpoint_context") or {},
        "decision_authority": "ENGINE_ADVISORY_ONLY",
        "planning_squad": {
            "authority": locked.get("squad_authority"),
            "baseline_gw": locked.get("baseline_gw"),
            "planning_gw": locked.get("planning_gw"),
            "override_active": locked.get("planning_override_active"),
            "target_gw": locked.get("target_gw"),
            "authority_source": locked.get("authority_source"),
            "wildcard_active": locked.get("wildcard_active"),
            "free_hit_active": locked.get("free_hit_active"),
            "free_transfers": locked.get("free_transfers"),
        },
        "understat_tactical": {
            "health": (understat_tactical.get("health") or {}).get("status") or "UNAVAILABLE",
            "freshness": (understat_tactical.get("source") or {}).get("freshness"),
            "close_call_only_for_lineup": True,
            "package_risk_enrichment_only": True,
            "direct_xpts_mutation": False,
            "direct_xmins_mutation": False,
        },
        "tactical_interaction": {
            "contract": tactical_interactions.get("contract"),
            "health": tactical_interactions.get("health") or {},
            "direct_xpts_mutation": False,
            "direct_xmins_mutation": False,
        },
        "full_universe_package_search": {
            "status": search.get("status"),
            "global_optimality_guaranteed_under_declared_package_semantics": search.get("global_optimality_guaranteed_under_declared_package_semantics"),
            "diagnostics": search.get("diagnostics") or {},
            "efficient_frontier_status": (packages.get("efficient_frontier") or {}).get("status"),
        },
        "timings": timings,
        "canonical_resolution": arbitration,
        "results": {
            "wc_raw": wc.get("classification"),
            "package_raw": packages.get("overall_verdict"),
            "recommendation_final": sanity.get("final_verdict"),
            "recommended_replacements": (sanity.get("recommended_package") or {}).get("replacements"),
            "transfer_candidate_state": ((arbitration.get("dimensions") or {}).get("transfer") or {}).get("candidate_state"),
            "overall_action": arbitration.get("overall_action"),
            "lineup_governance": (lineup.get("governance") or {}).get("decision"),
            "formation": lineup.get("formation"),
            "formation_state": lineup.get("formation_state"),
            "captain": (lineup.get("captain") or {}).get("name"),
        },
        "performance_guardrails": {
            "shared_json_loaded_once": True,
            "shared_candidates_built_once": True,
            "fork_copy_on_write": True,
            "parallel_wc_package": True,
            "parallel_lineup_with_wc_package": True,
            "full_universe_package_search": search.get("status") == "FULL_UNIVERSE_PROVEN",
            "heuristic_candidate_cutoff": bool(search.get("heuristic_candidate_cutoff")),
            "beam_cutoff": bool(search.get("beam_cutoff")),
            "search_quality_reduction": search.get("status") != "FULL_UNIVERSE_PROVEN",
            "checkpoint_action_deferred_until_postflight_health": True,
            "planning_squad_from_team_contract": True,
            "stale_lock_players_not_direct_optimizer_input": True,
            "engine_lineup_is_advisory_only": True,
            "manual_override_applied_in_separate_microservice": True,
            "canonical_decision_single_owner": True,
            "material_upgrade_alone_never_execution": True,
            "exact_semantic_optimizer_cache": True,
            "optimizer_cache_bounded_to_actual_consumers": True,
            "optimizer_cache_never_skips_sanity_tactical_or_arbitration": True,
            "optimizer_cache_artifact_digest_verified": True,
            "understat_network_io_excluded_from_decision_compute": True,
            "understat_no_direct_prediction_mutation": True,
            "price_projection_not_current_fact": True,
            "price_cannot_independently_authorize_transfer": True,
        },
    }
    if runtime_context is not None:
        runtime_context["predictions"] = predictions
        runtime_context["universe"] = universe
    atomic_json(OUTFILE, out)
    print(json.dumps({
        "engine": out["engine"],
        "overall_action": arbitration.get("overall_action"),
        "transfer_state": out["results"]["transfer_candidate_state"],
        "formation": lineup.get("formation"),
        "understat": out["understat_tactical"]["health"],
        "full_universe_search": out["full_universe_package_search"]["status"],
        "optimizer_cache_hit": hit,
        "semantic_fingerprint_ms": fingerprint_ms,
        "decision_parallel_wall_ms": parallel_wall,
        "package_audit_cpu_ms": statuses["packages"]["ms"],
        "lineup_cpu_ms": statuses["lineup"]["ms"],
        "total_pipeline_ms": timings["total_pipeline_ms"],
    }, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
