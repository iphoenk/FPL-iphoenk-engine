from __future__ import annotations

from collections import Counter

from src.utils import CONFIG, DATA, atomic_json, read_json

HEALTH = DATA / "framework_health_v4.json"
PREDICTIONS = DATA / "predictions_v4.json"
TACTICAL = DATA / "tactical_serving_v4.json"
COMPETITIVE_LOAD = DATA / "competitive_load_v4.json"
LATEST = DATA / "latest.json"
UNIVERSE = DATA / "universe.json"
POLICY = CONFIG / "recent_competitive_load.json"


def _find_module(health: dict, module_id: str) -> dict | None:
    for section in ("dss_core", "dss_extensions", "enhancements"):
        for row in (health.get(section) or {}).get("items") or []:
            if row.get("id") == module_id:
                return row
    return None


def _promote(row: dict | None, ok: bool, detail: dict) -> bool:
    if row is None:
        return False
    row["detail"] = detail
    if ok:
        row["status"] = "ACTIVE"
        return True
    return False


def _system_fit_evidence(predictions: dict, tactical: dict) -> tuple[bool, dict]:
    players = list(predictions.get("players") or [])
    fixtures: list[dict] = []
    for player in players:
        fixtures.extend(list(player.get("fixtures") or [])[:3])
    tactical_rows = [*(tactical.get("owned") or []), *(tactical.get("watchlist") or [])]
    roles = sum(bool((player.get("priors") or {}).get("tactical_role")) for player in players)
    fixture_context = sum(
        (fixture.get("calibration") or {}).get("fixture_adjustment") is not None
        and (fixture.get("calibration") or {}).get("opponent_defence_resistance") is not None
        for fixture in fixtures
    )
    tactical_complete = len(tactical.get("owned") or []) == 15 and len(tactical.get("watchlist") or []) == 20
    tactical_role_rows = sum(bool((row.get("tactical") or {}).get("player_role")) for row in tactical_rows)
    verified_external_rows = sum((row.get("tactical") or {}).get("evidence_state") == "VERIFIED" for row in tactical_rows)
    ok = bool(players) and roles == len(players) and bool(fixtures) and fixture_context == len(fixtures) and tactical_complete and tactical_role_rows == len(tactical_rows)
    return ok, {
        "implementation_state": "ACTIVE" if ok else "PARTIAL",
        "players": len(players),
        "player_roles": roles,
        "fixture_rows": len(fixtures),
        "fixture_context_rows": fixture_context,
        "tactical_owned": len(tactical.get("owned") or []),
        "tactical_watchlist": len(tactical.get("watchlist") or []),
        "tactical_role_rows": tactical_role_rows,
        "verified_external_tactical_rows": verified_external_rows,
        "external_evidence_state": "COMPLETE" if verified_external_rows == len(tactical_rows) and tactical_rows else "EVIDENCE_GATED",
        "evidence_semantics": "system/formation-fit computation is active from canonical player role + Official fixture/opponent calibration; verified external coach/shape observations are a separate evidence-richness dimension",
        "false_green_guard": "ACTIVE never implies that all 35 tactical rows have externally verified coach/shape evidence; unverified evidence cannot create a tactical delta",
    }


def _rotation_evidence(predictions: dict) -> tuple[bool, dict]:
    players = list(predictions.get("players") or [])
    priors = [player.get("priors") or {} for player in players]
    complete = sum(all(key in row for key in ("competition_pressure", "competition_source", "squad_depth_pressure", "competition_factor", "competition_adjustment_applied")) for row in priors)
    factors = [float(row.get("competition_factor", 1.0)) for row in priors]
    distinct = len({round(value, 4) for value in factors})
    bounded = all(0.72 <= value <= 1.0 for value in factors)
    source_rows = sum(bool(row.get("competition_source")) for row in priors)
    ok = bool(players) and complete == len(players) and source_rows == len(players) and distinct > 1 and bounded
    return ok, {
        "implementation_state": "ACTIVE" if ok else "PARTIAL",
        "players": len(players),
        "complete_rows": complete,
        "source_rows": source_rows,
        "distinct_competition_factors": distinct,
        "bounded_0_72_to_1": bounded,
        "reasoning": "per-player role competition is active when every player has canonical competition evidence and the factor varies across the universe; requiring at least one exactly-unadjusted player is not a valid maturity condition",
    }


def _schedule_capability_evidence(competitive: dict, policy: dict) -> tuple[bool, dict]:
    coverage = competitive.get("coverage") or {}
    handoff = policy.get("xmins_handoff") or {}
    guardrails = competitive.get("guardrails") or {}
    implementation_ok = policy.get("contract") == "RECENT_COMPETITIVE_LOAD_V2" and handoff.get("enabled") is True and handoff.get("direct_xpts_mutation_forbidden") is True and guardrails.get("official_fpl_acquisition_reused_not_refetched") is True and guardrails.get("recent_match_load_is_xmins_evidence_not_direct_points_evidence") is True and coverage.get("players", 0) > 0
    evidence_complete = coverage.get("complete_for_visible_report") is True
    return implementation_ok, {
        "implementation_state": "ACTIVE" if implementation_ok else "PARTIAL",
        "evidence_state": "COMPLETE" if evidence_complete else "EVIDENCE_GATED",
        "players": coverage.get("players"),
        "official_fpl_current_gw_load": coverage.get("official_fpl_current_gw_load"),
        "other_competitions": coverage.get("other_competitions"),
        "press_conference_collection": coverage.get("press_conference_collection"),
        "complete_for_visible_report": evidence_complete,
        "semantics": "module status measures production capability implementation; current external evidence completeness is reported separately and may not be fabricated",
    }


def _prior_evidence(predictions: dict, kind: str) -> tuple[bool, dict]:
    players = list(predictions.get("players") or [])
    if kind == "historical":
        covered = sum(bool((player.get("priors") or {}).get("prior_season_available")) or float((player.get("priors") or {}).get("last_season_weight", 0) or 0) > 0 for player in players)
        ok = bool(players) and covered > 0
        return ok, {
            "implementation_state": "ACTIVE" if ok else "PARTIAL",
            "players": len(players),
            "historical_prior_rows": covered,
            "semantics": "historical prior capability is active when canonical prior-season evidence is consumed for eligible players; promoted/new players may truthfully use fallback priors",
        }
    coverage = predictions.get("input_coverage") or {}
    consumer_active = coverage.get("preseason_consumer_active") is True and coverage.get("preseason_contract") == "PRESEASON_EVIDENCE_V1" and coverage.get("preseason_direct_xpts_mutation") is False
    preseason_rows = int(coverage.get("preseason_matched", 0) or 0)
    evidence_state = coverage.get("preseason_evidence_state") or "EVIDENCE_GATED"
    return consumer_active, {
        "implementation_state": "ACTIVE" if consumer_active else "PARTIAL",
        "consumer_contract": coverage.get("preseason_contract"),
        "source": coverage.get("preseason"),
        "preseason_rows": preseason_rows,
        "role_rows": int(coverage.get("preseason_role_rows", 0) or 0),
        "minutes_rows": int(coverage.get("preseason_minutes_rows", 0) or 0),
        "evidence_state": evidence_state,
        "direct_xpts_mutation": coverage.get("preseason_direct_xpts_mutation"),
        "semantics": "the production preseason capability is ACTIVE when its verified-evidence intake and canonical player-id join are wired; absence of current materialized evidence remains EVIDENCE_GATED and contributes no fabricated signal",
        "false_green_guard": "ACTIVE capability does not mean preseason observations are currently available; user-facing claims must disclose EVIDENCE_GATED when matched rows are zero",
    }


def _ownership_evidence(latest: dict, universe: dict) -> tuple[bool, dict]:
    official = latest.get("official_context") or {}
    players = list(universe.get("players") or [])
    ownership_rows = int(((official.get("player_field_coverage") or {}).get("ownership")) or 0)
    ok = bool(players) and official.get("official_fpl_first") is True and ownership_rows == len(players)
    return ok, {
        "implementation_state": "ACTIVE" if ok else "PARTIAL",
        "source": "Official FPL bootstrap-static elements.selected_by_percent",
        "players": len(players),
        "ownership_rows": ownership_rows,
        "effective_ownership_available_from_official_fpl": False,
        "semantics": "ownership context is active; effective ownership remains an optional external/advisory field and is not required to prove Official ownership capability",
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

    promotions: list[str] = []
    ok, detail = _system_fit_evidence(predictions, tactical)
    promotions += ["DSS-08"] if _promote(_find_module(health, "DSS-08"), ok, detail) else []
    ok, detail = _rotation_evidence(predictions)
    promotions += ["DSS-09"] if _promote(_find_module(health, "DSS-09"), ok, detail) else []

    schedule_ok, schedule_detail = _schedule_capability_evidence(competitive, policy)
    for module_id, label in (("DSS-30", "EUROPEAN"), ("DSS-31", "DOMESTIC_CUP"), ("DSS-32", "INTERNATIONAL"), ("DSS-33", "REST_RECOVERY")):
        detail = {**schedule_detail, "schedule_dimension": label}
        promotions += [module_id] if _promote(_find_module(health, module_id), schedule_ok, detail) else []

    ok, detail = _prior_evidence(predictions, "preseason")
    promotions += ["DSS-34"] if _promote(_find_module(health, "DSS-34"), ok, detail) else []
    ok, detail = _prior_evidence(predictions, "historical")
    promotions += ["DSS-36"] if _promote(_find_module(health, "DSS-36"), ok, detail) else []
    ok, detail = _ownership_evidence(latest, universe)
    promotions += ["DSS-41"] if _promote(_find_module(health, "DSS-41"), ok, detail) else []

    _recount(health)
    health["maturity_reconciliation"] = {
        "schema_version": 2,
        "promoted_modules": promotions,
        "promoted_count": len(promotions),
        "false_green_forbidden": True,
        "evidence_gaps_remain_visible": True,
        "critical_lists_rebuilt_after_promotions": True,
        "critical_warmup_blocks_unqualified_go": True,
        "note": "Engineering capability readiness is separated from current external-evidence completeness; critical readiness is recomputed from the post-promotion module state and data-dependent warmup remains truthful.",
    }
    atomic_json(HEALTH, health)
    return health
