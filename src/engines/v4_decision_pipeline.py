from __future__ import annotations

import hashlib
import json
import traceback
from multiprocessing import get_context
from pathlib import Path
from time import perf_counter

from src.engines.v4_decision_arbitration import OUTFILE as ARBITRATION_OUTFILE, resolve_decision
from src.engines.v4_lineup_optimizer import optimize_lineup
from src.engines.v4_recommendation_sanity import sanity_report
from src.engines.v4_tactical_serving import build_tactical_serving
from src.engines.v4_wc_optimizer import build_candidates
from src.engines.v4_wc_optimizer_fast import decision_report_from_candidates_fast
from src.engines.v4_wc_package_audit_fast import audit_packages_from_candidates_fast
from src.services.contracts import file_digest
from src.utils import CONFIG, DATA, atomic_json, read_json

OUTFILE = DATA / "decision_pipeline_v4.json"
TACTICAL_OUTFILE = DATA / "tactical_serving_v4.json"
DECISION_CACHE = DATA / "decision_hot_cache_v4.json"
WC_OUTFILE = DATA / "wc_decision_v4.json"
PACKAGE_OUTFILE = DATA / "wc_package_audit_v4.json"
LINEUP_OUTFILE = DATA / "lineup_decision_v4.json"
CACHE_ALGORITHM = "v4.9.6-exact-semantic-decision-cache-v2"
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
    return {
        "players": players,
        "itb_tenths": int((team.get("totals") or {}).get("itb") or 0),
        "wildcard_active": wildcard_for_planning,
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
            atomic_json(WC_OUTFILE, out)
        elif kind == "packages":
            out = audit_packages_from_candidates_fast(shared["candidates"], shared["locked"])
            atomic_json(PACKAGE_OUTFILE, out)
        elif kind == "lineup":
            out = optimize_lineup(shared["predictions"], shared["universe"], shared["locked"], manual=None)
            atomic_json(LINEUP_OUTFILE, out)
        else:
            raise RuntimeError(f"unknown decision worker: {kind}")
        conn.send({"ok": True, "ms": round((perf_counter() - t) * 1000.0, 1)})
    except Exception:
        conn.send({"ok": False, "ms": round((perf_counter() - t) * 1000.0, 1), "error": traceback.format_exc()})
    finally:
        conn.close()


def _run_parallel_decisions(candidates, locked, predictions, universe):
    global _SHARED
    _SHARED = {"candidates": candidates, "locked": locked, "predictions": predictions, "universe": universe}
    ctx = get_context("fork")
    workers = {}
    wall = perf_counter()
    for kind, name in (("wc", "v496-wc-fast"), ("packages", "v496-packages-fast"), ("lineup", "v496-lineup")):
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
    """Compact exact semantics consumed by WC/package optimizers.

    The Candidate object is already the canonical normalization boundary for those
    optimizers. Hashing it avoids recursively serializing prediction provenance that
    cannot affect WC/package outputs while preserving exact cache invalidation for
    every field the optimizers can read.
    """
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


def _lineup_semantics(predictions: dict, universe: dict, locked: dict) -> list[dict]:
    """Hash exactly the fields consumed by optimize_lineup(manual=None).

    This deliberately excludes timestamps, provenance blobs, external tactical
    serving evidence and unowned player detail because none can affect the cached
    lineup artifact. Sanity, tactical serving and arbitration are never cached and
    still consume the full current prediction/universe payload every run.
    """
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
        })
    return rows


def _semantic_fingerprint(predictions: dict, universe: dict, locked: dict, candidates=None) -> str:
    """Hash exact inputs of cached WC/package/lineup artifacts, not whole payloads.

    Candidate normalization covers WC/package semantics. A separate owned-player
    projection covers lineup semantics. This reduces fingerprint complexity from a
    recursive full-payload walk to a bounded compact projection while remaining
    exact for the three cached artifacts.
    """
    normalized_candidates = candidates if candidates is not None else build_candidates(predictions, universe)
    serving_policy = read_json(CONFIG / "serving_improvement_registry.json", {}) or {}
    payload = {
        "algorithm": CACHE_ALGORITHM,
        "prediction_model": predictions.get("model_version"),
        "candidate_semantics": _candidate_semantics(normalized_candidates),
        "lineup_semantics": _lineup_semantics(predictions, universe, locked),
        "planning_squad": locked,
        "lineup_policy": serving_policy.get("lineup") or {},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _cache_artifacts() -> dict[str, Path]:
    return {
        "wc": WC_OUTFILE,
        "packages": PACKAGE_OUTFILE,
        "lineup": LINEUP_OUTFILE,
    }


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
        "schema_version": 2,
        "algorithm": CACHE_ALGORITHM,
        "fingerprint": fingerprint,
        "artifact_sha256": {key: file_digest(path) for key, path in _cache_artifacts().items()},
        "guardrails": {
            "exact_semantic_inputs_only": True,
            "bounded_consumer_projection_not_full_payload": True,
            "runtime_timestamps_not_consumed_by_cache_key": True,
            "artifact_digest_verified_before_reuse": True,
            "manual_user_override_not_cached": True,
            "sanity_tactical_arbitration_rerun_every_time": True,
            "search_width_unchanged": True,
        },
    })


def run(*, runtime_context: dict | None = None):
    t0 = perf_counter()
    predictions = read_json(DATA / "predictions_v4.json", {})
    universe = read_json(DATA / "universe.json", {})
    configured_lock = read_json(CONFIG / "locked_squad.json", {})
    team = read_json(DATA / "team.json", {})
    latest = read_json(DATA / "latest.json", {})
    locked = effective_planning_squad(team, configured_lock, latest)
    load_ms = round((perf_counter() - t0) * 1000.0, 1)

    t = perf_counter()
    candidates = build_candidates(predictions, universe)
    candidates_ms = round((perf_counter() - t) * 1000.0, 1)

    t = perf_counter()
    fingerprint = _semantic_fingerprint(predictions, universe, locked, candidates=candidates)
    fingerprint_ms = round((perf_counter() - t) * 1000.0, 1)
    timings = {
        "load_shared_inputs_ms": load_ms,
        "build_candidates_ms": candidates_ms,
        "semantic_fingerprint_ms": fingerprint_ms,
        "load_shared_inputs_candidates_and_fingerprint_ms": round(load_ms + candidates_ms + fingerprint_ms, 1),
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
        statuses, parallel_wall = _run_parallel_decisions(candidates, locked, predictions, universe)
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
    tactical = build_tactical_serving(predictions, universe, team, previous=previous_tactical)
    atomic_json(TACTICAL_OUTFILE, tactical)
    timings["tactical_serving_ms"] = round((perf_counter() - t) * 1000.0, 1)

    t = perf_counter()
    arbitration = resolve_decision(sanity, lineup, latest, team, read_json(DATA / "prices.json", {}), tactical, predictions)
    atomic_json(ARBITRATION_OUTFILE, arbitration)
    timings["decision_arbitration_ms"] = round((perf_counter() - t) * 1000.0, 1)
    timings["total_pipeline_ms"] = round((perf_counter() - t0) * 1000.0, 1)

    out = {
        "schema_version": 4962,
        "engine": "v4.9.6-unified-decision-pipeline-canonical-arbitration",
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
            "exact_streaming_top_packages": bool((packages.get("performance") or {}).get("exact_streaming_top_packages")),
            "stable_top_package_tie_semantics": bool((packages.get("performance") or {}).get("stable_top_package_tie_semantics")),
            "search_quality_reduction": False,
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
        },
    }
    if runtime_context is not None:
        # Same-process immutable reuse only. These objects were parsed from
        # the governed prediction/universe artifacts above; the weather
        # overlay would otherwise parse the identical files again.
        runtime_context["predictions"] = predictions
        runtime_context["universe"] = universe
    atomic_json(OUTFILE, out)
    print(json.dumps({
        "engine": out["engine"],
        "overall_action": arbitration.get("overall_action"),
        "transfer_state": out["results"]["transfer_candidate_state"],
        "formation": lineup.get("formation"),
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