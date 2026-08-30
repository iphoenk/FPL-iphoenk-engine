from __future__ import annotations

from collections import Counter

from src.engines.v4_backtest_store import reconciled_integrity
from src.engines.v4_validation import promotion_gate
from src.utils import CONFIG, DATA, atomic_json, read_json

HEALTH = DATA / "framework_health_v4.json"
PREDICTIONS = DATA / "predictions_v4.json"
TACTICAL = DATA / "tactical_serving_v4.json"
COMPETITIVE_LOAD = DATA / "competitive_load_v4.json"
LATEST = DATA / "latest.json"
UNIVERSE = DATA / "universe.json"
POLICY = CONFIG / "recent_competitive_load.json"
RECONCILED = DATA / "validation" / "reconciled"
MATURE_MODULES = ("DSS-08", "DSS-09", "DSS-30", "DSS-31", "DSS-32", "DSS-33", "DSS-34", "DSS-36", "DSS-41")
CALIBRATION_WARMUP_MODULES = ("DSS-44", "DSS-X12")
CALIBRATION_MINIMUM_N = 300


def _find_module(health: dict, module_id: str) -> dict | None:
    for section in ("dss_core", "dss_extensions", "enhancements"):
        for row in (health.get(section) or {}).get("items") or []:
            if row.get("id") == module_id:
                return row
    return None


def _set_readiness(row: dict | None, ok: bool, detail: dict) -> bool:
    if row is None:
        return False
    row["detail"] = detail
    row["status"] = "ACTIVE" if ok else "PARTIAL"
    return ok


def _system_fit_evidence(predictions: dict, tactical: dict) -> tuple[bool, dict]:
    players = list(predictions.get("players") or [])
    fixtures = [fixture for player in players for fixture in list(player.get("fixtures") or [])[:3]]
    owned = list(tactical.get("owned") or [])
    watchlist = list(tactical.get("watchlist") or [])
    tactical_rows = [*owned, *watchlist]
    guardrails = tactical.get("guardrails") or {}
    roles = sum(bool((player.get("priors") or {}).get("tactical_role")) for player in players)
    fixture_context = sum(
        (fixture.get("calibration") or {}).get("fixture_adjustment") is not None
        and (fixture.get("calibration") or {}).get("opponent_defence_resistance") is not None
        for fixture in fixtures
    )
    tactical_role_rows = sum(bool((row.get("tactical") or {}).get("player_role")) for row in tactical_rows)
    verified_external_rows = sum(
        (row.get("tactical") or {}).get("external_evidence_state") == "VERIFIED"
        or (
            (row.get("tactical") or {}).get("external_evidence_state") is None
            and (row.get("tactical") or {}).get("evidence_state") == "VERIFIED"
        )
        for row in tactical_rows
    )
    unsupported_deltas = sum(
        abs(float((row.get("tactical") or {}).get("tactical_delta_applied") or 0)) > 1e-9
        for row in tactical_rows
        if (row.get("tactical") or {}).get("external_evidence_state", "EVIDENCE_GATED") != "VERIFIED"
        and (row.get("tactical") or {}).get("evidence_state") != "VERIFIED"
    )
    tactical_complete = (
        tactical.get("contract") == "TACTICAL_SERVING_15_20_V1"
        and len(owned) == 15
        and len(watchlist) == 20
        and guardrails.get("exact_15_owned") is True
        and guardrails.get("exact_20_watchlist") is True
        and guardrails.get("unverified_tactical_delta_is_zero") is True
    )
    ok = (
        bool(players)
        and roles == len(players)
        and bool(fixtures)
        and fixture_context == len(fixtures)
        and tactical_complete
        and tactical_role_rows == len(tactical_rows)
        and unsupported_deltas == 0
    )
    return ok, {
        "implementation_state": "ACTIVE" if ok else "PARTIAL",
        "players": len(players),
        "player_roles": roles,
        "fixture_rows": len(fixtures),
        "fixture_context_rows": fixture_context,
        "tactical_owned": len(owned),
        "tactical_watchlist": len(watchlist),
        "tactical_role_rows": tactical_role_rows,
        "verified_external_tactical_rows": verified_external_rows,
        "unsupported_external_tactical_deltas": unsupported_deltas,
        "external_evidence_state": "COMPLETE" if verified_external_rows == len(tactical_rows) and tactical_rows else "EVIDENCE_GATED",
        "evidence_semantics": "canonical player role and Official fixture/opponent calibration are implementation evidence; verified coach/shape evidence is a separate richness dimension",
        "false_green_guard": "unverified coach/shape evidence contributes zero tactical delta",
    }


def _rotation_evidence(predictions: dict) -> tuple[bool, dict]:
    players = list(predictions.get("players") or [])
    priors = [player.get("priors") or {} for player in players]
    required = (
        "competition_pressure",
        "competition_source",
        "squad_depth_pressure",
        "competition_factor",
        "competition_adjustment_applied",
    )
    complete = sum(all(key in row for key in required) for row in priors)
    factors = [float(row.get("competition_factor", 1.0)) for row in priors]
    distinct = len({round(value, 4) for value in factors})
    bounded = all(0.72 <= value <= 1.0 for value in factors)
    source_rows = sum(row.get("competition_source") == "inferred_tactical_role_peer_group" for row in priors)
    broad_diagnostics = sum(row.get("competition_source") == "broad_fpl_position_diagnostic_only" for row in priors)
    semantic_rows = sum(
        bool(row.get("competition_adjustment_applied")) == (float(row.get("competition_factor", 1.0)) < 1 - 1e-6)
        for row in priors
    )
    ok = (
        bool(players)
        and complete == len(players)
        and source_rows == len(players)
        and broad_diagnostics == 0
        and semantic_rows == len(players)
        and distinct > 1
        and bounded
    )
    return ok, {
        "implementation_state": "ACTIVE" if ok else "PARTIAL",
        "players": len(players),
        "complete_rows": complete,
        "canonical_per_player_source_rows": source_rows,
        "broad_position_diagnostic_rows": broad_diagnostics,
        "semantic_consistency_rows": semantic_rows,
        "distinct_competition_factors": distinct,
        "bounded_0_72_to_1": bounded,
        "reasoning": "per-player tactical-role peer competition is materialized for every player; no exactly-unadjusted-player requirement is imposed",
    }


def _schedule_capability_evidence(
    competitive: dict,
    policy: dict,
    predictions: dict,
    module_id: str,
) -> tuple[bool, dict]:
    coverage = competitive.get("coverage") or {}
    handoff = policy.get("xmins_handoff") or {}
    guardrails = competitive.get("guardrails") or {}
    prediction_capability = predictions.get("capability_evidence") or {}
    prediction_guardrails = predictions.get("guardrails") or {}
    dimensions = {
        "DSS-30": ("EUROPEAN", "european_verified_player_fixture_rows"),
        "DSS-31": ("DOMESTIC_CUP", "domestic_cup_verified_player_fixture_rows"),
        "DSS-32": ("INTERNATIONAL", "international_verified_player_fixture_rows"),
        "DSS-33": ("REST_RECOVERY", "observed_player_fixture_rows"),
    }
    dimension, count_key = dimensions[module_id]
    implementation_ok = (
        competitive.get("schema") == "competitive_load.v1"
        and policy.get("contract") == "RECENT_COMPETITIVE_LOAD_V2"
        and handoff.get("enabled") is True
        and handoff.get("direct_xpts_mutation_forbidden") is True
        and guardrails.get("official_fpl_acquisition_reused_not_refetched") is True
        and guardrails.get("verified_external_competitive_intake_wired") is True
        and guardrails.get("unverified_external_competitive_signal_is_zero") is True
        and guardrails.get("recent_match_load_is_xmins_evidence_not_direct_points_evidence") is True
        and dimension in set(coverage.get("implemented_dimensions") or [])
        and prediction_capability.get("competitive_load_consumer_active") is True
        and prediction_guardrails.get("competitive_load_direct_xpts_mutation_forbidden") is True
        and prediction_guardrails.get("competitive_load_direct_start_probability_mutation_forbidden") is True
        and coverage.get("players", 0) > 0
    )
    verified_rows = int(coverage.get(count_key, 0) or 0)
    return implementation_ok, {
        "implementation_state": "ACTIVE" if implementation_ok else "PARTIAL",
        "schedule_dimension": dimension,
        "evidence_state": "VERIFIED" if verified_rows > 0 else "EVIDENCE_GATED",
        "verified_player_fixture_rows": verified_rows,
        "players": coverage.get("players"),
        "official_fpl_current_gw_load": coverage.get("official_fpl_current_gw_load"),
        "other_competitions": coverage.get("other_competitions"),
        "press_conference_collection": coverage.get("press_conference_collection"),
        "complete_for_visible_report": coverage.get("complete_for_visible_report") is True,
        "downstream_xmins_consumer_active": prediction_capability.get("competitive_load_consumer_active") is True,
        "semantics": "implementation readiness and current optional external-evidence completeness are separate; missing verified rows create no signal",
    }


def _prior_evidence(predictions: dict, kind: str) -> tuple[bool, dict]:
    players = list(predictions.get("players") or [])
    coverage = predictions.get("input_coverage") or {}
    if kind == "historical":
        consumed = sum(
            float((player.get("priors") or {}).get("last_season_weight", 0) or 0) > 0
            and bool((player.get("priors") or {}).get("last_season_source"))
            for player in players
        )
        ok = bool(players) and int(coverage.get("last_season_matched", 0) or 0) > 0 and consumed > 0
        return ok, {
            "implementation_state": "ACTIVE" if ok else "PARTIAL",
            "players": len(players),
            "historical_prior_rows_consumed": consumed,
            "historical_input_matches": int(coverage.get("last_season_matched", 0) or 0),
            "fallback_allowed": True,
            "semantics": "eligible players consume canonical prior-season evidence; promoted/new players may truthfully use fallback without fabricated rows",
        }
    guardrails = predictions.get("guardrails") or {}
    consumer_active = (
        coverage.get("preseason_consumer_active") is True
        and coverage.get("preseason_contract") == "PRESEASON_EVIDENCE_V1"
        and coverage.get("preseason_identity_join") == "official_element_id"
        and coverage.get("preseason_direct_xpts_mutation") is False
        and guardrails.get("preseason_unverified_signal_zero") is True
        and guardrails.get("preseason_direct_xpts_mutation") is False
    )
    return consumer_active, {
        "implementation_state": "ACTIVE" if consumer_active else "PARTIAL",
        "consumer_contract": coverage.get("preseason_contract"),
        "source": coverage.get("preseason"),
        "preseason_rows": int(coverage.get("preseason_matched", 0) or 0),
        "role_rows": int(coverage.get("preseason_role_rows", 0) or 0),
        "role_rows_consumed": int((predictions.get("capability_evidence") or {}).get("preseason_role_consumed", 0) or 0),
        "minutes_rows": int(coverage.get("preseason_minutes_rows", 0) or 0),
        "evidence_state": coverage.get("preseason_evidence_state") or "EVIDENCE_GATED",
        "direct_xpts_mutation": coverage.get("preseason_direct_xpts_mutation"),
        "semantics": "verified current-season evidence is joined by Official element id before projection; missing materialization remains evidence-gated and contributes zero signal",
    }


def _ownership_evidence(latest: dict, universe: dict, predictions: dict) -> tuple[bool, dict]:
    official = latest.get("official_context") or {}
    players = list(universe.get("players") or [])
    prediction_players = list(predictions.get("players") or [])
    capability = predictions.get("capability_evidence") or {}
    ownership_rows = int(((official.get("player_field_coverage") or {}).get("ownership")) or 0)
    universe_rows = sum(row.get("ownership") is not None for row in players)
    consumed = int(capability.get("ownership_context_consumed_players", 0) or 0)
    ok = (
        bool(players)
        and official.get("official_fpl_first") is True
        and ownership_rows == len(players)
        and universe_rows == len(players)
        and int(capability.get("official_ownership_rows", 0) or 0) == len(prediction_players)
        and consumed == len(prediction_players)
        and bool(prediction_players)
    )
    return ok, {
        "implementation_state": "ACTIVE" if ok else "PARTIAL",
        "source": "Official FPL bootstrap-static elements.selected_by_percent",
        "players": len(players),
        "ownership_rows": ownership_rows,
        "universe_ownership_rows": universe_rows,
        "prediction_consumed_rows": consumed,
        "effective_ownership_available_from_official_fpl": False,
        "effective_ownership_state": "OPTIONAL_EXTERNAL_ADVISORY",
        "semantics": "Official ownership is authoritative and consumed in prediction priors; effective ownership is optional external advisory evidence",
    }


def _calibration_maturity_evidence(predictions: dict) -> tuple[bool, dict]:
    model_version = predictions.get("model_version")
    paths = sorted(RECONCILED.glob("gw*.json")) if RECONCILED.exists() else []
    eligible: list[dict] = []
    rejected: list[dict] = []
    passing: list[dict] = []
    best_observed_n = 0

    for path in paths:
        sample = read_json(path, {})
        ok, reason = reconciled_integrity(sample, model_version=model_version)
        if not ok:
            rejected.append({"file": path.name, "reason": reason})
            continue
        gw = int(sample.get("gw") or 0)
        metrics = ((sample.get("report") or {}).get("metrics") or {})
        observed_n = int(metrics.get("n") or 0)
        best_observed_n = max(best_observed_n, observed_n)
        gate = promotion_gate(sample.get("report") or {}, minimum_n=CALIBRATION_MINIMUM_N)
        row = {
            "file": path.name,
            "gw": gw,
            "n": observed_n,
            "mae": metrics.get("mae"),
            "spearman": (metrics.get("ranking") or {}).get("spearman"),
            "interval80_coverage": metrics.get("interval80_coverage"),
            "promotion": gate,
        }
        eligible.append(row)
        if gate.get("promote") is True:
            passing.append(row)

    active = bool(passing)
    return active, {
        "implementation_state": "ACTIVE" if active else "WARMUP",
        "model_version": model_version,
        "eligible_reconciled_samples": len(eligible),
        "eligible_gws": [row["gw"] for row in eligible],
        "rejected_samples": rejected,
        "passing_gws": [row["gw"] for row in passing],
        "best_observed_n": best_observed_n,
        "minimum_n": CALIBRATION_MINIMUM_N,
        "promotion_rule": "at least one immutable current-model reconciliation must pass canonical v4_validation.promotion_gate",
        "quality_requirements": {
            "mae_max": 3.5,
            "spearman_min": 0.15,
            "interval80_coverage_if_present": [0.65, 0.92],
        },
        "evidence_artifact": "data/validation/reconciled/gw*.json",
        "immutable_archive": "data/validation/archive/reconciled/gw*.json",
        "completed_gw_reconciliation_feeds_evidence": True,
        "deterministic_promotion": True,
        "synthetic_or_invalid_samples_rejected_by_integrity_check": True,
        "official_start_truth": "raw_snapshot.official.event_live.stats.starts",
        "missing_starts_excluded_from_start_brier": True,
        "retrospective_mutation_prevented": True,
        "reason": None if active else "calibration implementation is ready but genuine immutable production evidence has not yet passed the canonical promotion gate",
    }


def _recount(health: dict) -> None:
    totals = Counter()
    critical_failed: list[str] = []
    critical_partial: list[str] = []
    critical_warmup: list[str] = []
    for section in ("dss_core", "dss_extensions", "enhancements"):
        block = health.get(section) or {}
        items = list(block.get("items") or [])
        counts = Counter(row.get("status") for row in items)
        block["counts"] = dict(counts)
        totals.update(counts)
        for row in items:
            if not row.get("critical"):
                continue
            status = row.get("status")
            module_id = row.get("id")
            if status == "FAILED":
                critical_failed.append(module_id)
            elif status == "PARTIAL":
                critical_partial.append(module_id)
            elif status == "WARMUP":
                critical_warmup.append(module_id)
    active = totals.get("ACTIVE", 0)
    partial = totals.get("PARTIAL", 0)
    warmup = totals.get("WARMUP", 0)
    failed = totals.get("FAILED", 0)
    declared = active + partial + warmup + failed
    health["critical_failed"] = critical_failed
    health["critical_partial"] = critical_partial
    health["critical_warmup"] = critical_warmup
    health["capability_coverage"] = {
        "active": active,
        "warmup": warmup,
        "partial": partial,
        "failed": failed,
        "declared": declared,
        "active_ratio": round(active / max(1, declared), 4),
    }
    health["capability_health"] = "RED" if failed else "AMBER" if partial or warmup else "GREEN"
    if critical_failed:
        health["prediction_health"] = "RED"
        health["decision_engine"] = "BLOCKED"
        health["go_allowed"] = False
    elif critical_partial:
        health["prediction_health"] = "AMBER"
        health["decision_engine"] = "DEGRADED"
        health["go_allowed"] = False
    elif critical_warmup:
        health["prediction_health"] = "AMBER"
        health["decision_engine"] = "PROVISIONAL"
        health["go_allowed"] = False
    else:
        health["prediction_health"] = "GREEN"
        health["decision_engine"] = "HEALTHY"
        health["go_allowed"] = True


def reconcile(health: dict | None = None) -> dict:
    health = health if health is not None else read_json(HEALTH, {})
    if not health:
        raise RuntimeError("maturity reconciliation requires framework health artifact")
    predictions = read_json(PREDICTIONS, {})
    tactical = read_json(TACTICAL, {})
    competitive = read_json(COMPETITIVE_LOAD, {})
    latest = read_json(LATEST, {})
    universe = read_json(UNIVERSE, {})
    policy = read_json(POLICY, {})

    active: list[str] = []
    partial: list[str] = []
    proofs: dict[str, tuple[bool, dict]] = {}
    proofs["DSS-08"] = _system_fit_evidence(predictions, tactical)
    proofs["DSS-09"] = _rotation_evidence(predictions)
    for module_id in ("DSS-30", "DSS-31", "DSS-32", "DSS-33"):
        proofs[module_id] = _schedule_capability_evidence(competitive, policy, predictions, module_id)
    proofs["DSS-34"] = _prior_evidence(predictions, "preseason")
    proofs["DSS-36"] = _prior_evidence(predictions, "historical")
    proofs["DSS-41"] = _ownership_evidence(latest, universe, predictions)

    for module_id in MATURE_MODULES:
        ok, detail = proofs[module_id]
        if _set_readiness(_find_module(health, module_id), ok, detail):
            active.append(module_id)
        else:
            partial.append(module_id)

    calibration_active, calibration_detail = _calibration_maturity_evidence(predictions)
    for module_id in CALIBRATION_WARMUP_MODULES:
        row = _find_module(health, module_id)
        if row is None:
            continue
        row["status"] = "ACTIVE" if calibration_active else "WARMUP"
        row["detail"] = {**calibration_detail, "module_id": module_id}

    _recount(health)
    health["maturity_reconciliation"] = {
        "schema_version": 4,
        "evaluated_modules": list(MATURE_MODULES),
        "active_modules": active,
        "partial_modules": partial,
        "warmup_modules": list(CALIBRATION_WARMUP_MODULES) if not calibration_active else [],
        "false_green_forbidden": True,
        "failed_proof_demotes_active_to_partial": True,
        "evidence_gaps_remain_visible": True,
        "critical_lists_rebuilt_after_reconciliation": True,
        "critical_warmup_blocks_unqualified_go": True,
        "calibration_promotion_gate_enforced": True,
        "note": "Capability readiness is recomputed from concrete producer-consumer evidence; current optional external evidence remains a separate evidence-state dimension, and calibration warmup promotes only on immutable current-model evidence that passes the canonical quality gate.",
    }
    atomic_json(HEALTH, health)
    return health