from __future__ import annotations

import json
from pathlib import Path

from src.engines.tactical_decision_consumption import apply_report_overlay
from src.utils import DATA, ROOT, atomic_json

REGISTRY = ROOT / "config" / "report_artifact_registry.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _watch_ids(positions: dict) -> list[int]:
    return [int(row["element"]) for rows in positions.values() for row in rows]


def _element_ids(rows: list[dict]) -> set[int]:
    return {int(row["element"]) for row in rows if row.get("element") is not None}


def _watch_ids_by_position(positions: dict, ordered_positions: list[str]) -> dict[str, set[int]]:
    return {
        position: _element_ids([row for row in positions.get(position) or [] if isinstance(row, dict)])
        for position in ordered_positions
    }


def _validate_owned_transparency(name: str, rows: list[dict], expected: int, contract: dict) -> None:
    assert len(rows) == expected, (name, len(rows), expected)
    assert len({int(row["element"]) for row in rows}) == expected
    if contract.get("owned_rows_require_current_gw_xpts"):
        assert all(row.get("xpts_gw") is not None for row in rows), (name, "missing_xpts")
        assert all(row.get("xpts_std") is not None for row in rows), (name, "missing_xpts_std")
    if contract.get("owned_rows_require_selection_score"):
        assert all(row.get("selection_score") is not None for row in rows), (name, "missing_selection_score")
    if contract.get("owned_rows_require_lineup_status"):
        assert all(row.get("lineup_status") in {"START", "BENCH"} for row in rows), (name, "invalid_lineup_status")
    if contract.get("owned_rows_require_choice_state"):
        assert all(row.get("choice_state") in {"OPEN", "CURRENT"} for row in rows), (name, "invalid_choice_state")


def _validate_compact_personal_gameweek_context(payload_name: str, payload: dict, context: dict) -> None:
    assert payload_name == "brief", (payload_name, "compact context only allowed on fast brief")
    assert context.get("fast_surface_compacted") is True, payload_name
    assert context.get("detail_ref") == "data/deep_review_payload.json#gameweek_context", payload_name
    planning = context.get("planning") or {}
    assert planning.get("status") == "PROJECTION", (payload_name, planning)
    assert planning.get("estimated_points") is not None, payload_name
    assert planning.get("decision_authority") in {"ENGINE_RECOMMENDATION", "USER_OVERRIDE"}, payload_name
    assert isinstance(planning.get("starting_xi"), list) and len(planning.get("starting_xi") or []) == 11, payload_name
    assert isinstance(planning.get("bench"), list) and len(planning.get("bench") or []) == 4, payload_name
    assert isinstance(planning.get("captain"), dict) and planning.get("captain"), payload_name
    assert isinstance(planning.get("vice_captain"), dict) and planning.get("vice_captain"), payload_name
    if planning.get("user_override_active"):
        assert planning.get("decision_authority") == "USER_OVERRIDE", payload_name
    historical = context.get("historical") or []
    assert len(historical) <= 2, (payload_name, len(historical))
    for row in historical:
        assert row.get("status") == "FINAL", (payload_name, row)
        assert row.get("authority") == "PUBLIC_OFFICIAL_POST_DEADLINE", (payload_name, row)
        assert row.get("actual_points") is not None, (payload_name, row)


def _validate_personal_gameweek_context(payload_name: str, payload: dict) -> None:
    context = payload.get("gameweek_context") or {}
    assert context.get("schema") == "personal_gameweek_context.v1", (payload_name, context.get("schema"))
    if context.get("fast_surface_compacted") is True:
        _validate_compact_personal_gameweek_context(payload_name, payload, context)
        return

    planning = context.get("planning") or {}
    assert planning.get("status") == "PROJECTION", (payload_name, planning)
    assert planning.get("estimated_points") is not None, payload_name
    assert planning.get("decision_authority") in {"ENGINE_RECOMMENDATION", "USER_OVERRIDE"}, payload_name
    assert (planning.get("scoring_guardrails") or {}).get("estimate_not_actual") is True, payload_name
    baseline = planning.get("baseline") or {}
    assert baseline.get("default_rule") == "PLANNING_GW_FROM_PREVIOUS_OFFICIAL_SUBMITTED_SQUAD", (payload_name, baseline)
    if planning.get("user_override_active"):
        assert planning.get("decision_authority") == "USER_OVERRIDE", payload_name
        assert (planning.get("comparison") or {}).get("engine_can_warn_but_not_overwrite_user") is True, payload_name
    for row in context.get("historical") or []:
        assert row.get("status") == "FINAL", (payload_name, row)
        assert row.get("authority") == "PUBLIC_OFFICIAL_POST_DEADLINE", (payload_name, row)
        assert row.get("actual_points") is not None, payload_name
        assert row.get("forecast_capture") == "NOT_RECONSTRUCTED", (payload_name, row)
        assert len(row.get("submitted_squad") or []) == 15, (payload_name, row.get("gw"))
    governance = context.get("governance") or {}
    assert governance.get("historical_truth_never_reconstructed_as_old_forecast") is True, payload_name
    assert governance.get("engine_recommendation_remains_visible_for_comparison") is True, payload_name


def _normalise_public_tactical_fields(value):
    if isinstance(value, list):
        return [_normalise_public_tactical_fields(item) for item in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, item in value.items():
        public_key = "observed_shape" if key == "verified_shape" else key
        out[public_key] = _normalise_public_tactical_fields(item)
    return out


def _battle_dict(payload: dict) -> dict:
    if isinstance(((payload.get("starting_xi") or {}).get("model") or {}).get("battle"), dict):
        return ((payload.get("starting_xi") or {}).get("model") or {}).get("battle") or {}
    value = payload.get("main_starting_xi_battle")
    return value if isinstance(value, dict) else {}


def _sync_battle_outcome(payload: dict, lineup: dict) -> None:
    battle = _battle_dict(payload)
    if not battle:
        return
    starter = str(battle.get("starter") or "")
    challenger = str(battle.get("challenger") or "")
    if not starter or not challenger:
        return
    final_starters = {str(row.get("name") or "") for row in lineup.get("starting_xi") or []}
    if challenger in final_starters and starter not in final_starters:
        battle["starter"], battle["challenger"] = challenger, starter
        leader = battle.get("leader_metrics")
        challenger_metrics = battle.get("challenger_metrics")
        if isinstance(leader, dict) and isinstance(challenger_metrics, dict):
            battle["leader_metrics"], battle["challenger_metrics"] = challenger_metrics, leader
        battle["tactical_outcome_note"] = "matchup lawan memecahkan battle yang sangat dekat; kandidat model awal tetap disimpan sebagai pembanding"


def _first_highlight(value: dict) -> str | None:
    tactical = value.get("tactical_matchup") or {}
    rows = tactical.get("highlights") or []
    return str(rows[0]) if rows else None


def _owned_rows(payload: dict) -> list[dict]:
    if isinstance(payload.get("owned_squad"), dict):
        return [row for row in (payload.get("owned_squad") or {}).get("facts") or [] if isinstance(row, dict)]
    return [row for row in payload.get("owned_15") or [] if isinstance(row, dict)]


def _authority_captain(payload: dict) -> tuple[str, dict]:
    planning = ((payload.get("gameweek_context") or {}).get("planning") or {})
    authority = str(planning.get("decision_authority") or "")
    captain = planning.get("captain") if isinstance(planning.get("captain"), dict) else {}
    if not captain:
        current = payload.get("current_team") if isinstance(payload.get("current_team"), dict) else {}
        captain = {"name": current.get("captain")}
    return authority, captain


def _owned_player_row(payload: dict, player: dict) -> dict:
    element = player.get("element")
    name = str(player.get("name") or "").casefold()
    for row in _owned_rows(payload):
        if element is not None and row.get("element") is not None and int(row.get("element")) == int(element):
            return row
        if name and str(row.get("name") or "").casefold() == name:
            return row
    return {}


def _tactical_presentation_note(payload: dict) -> str:
    notes: list[str] = []
    battle = _battle_dict(payload)
    if battle:
        starter = str(battle.get("starter") or "")
        challenger = str(battle.get("challenger") or "")
        leader = battle.get("leader_metrics") if isinstance(battle.get("leader_metrics"), dict) else {}
        challenge = battle.get("challenger_metrics") if isinstance(battle.get("challenger_metrics"), dict) else {}
        lead_note = _first_highlight(leader)
        challenge_note = _first_highlight(challenge)
        if starter and challenger and (lead_note or challenge_note):
            notes.append(f"Battle XI {starter} vs {challenger}: {lead_note or challenge_note}")

    authority, active_captain = _authority_captain(payload)
    active_name = str(active_captain.get("name") or "")
    if authority == "USER_OVERRIDE" and active_name:
        active_row = _owned_player_row(payload, active_captain)
        active_note = _first_highlight(active_row)
        if active_note:
            notes.append(f"Kapten aktif {active_name}: {active_note}")
        else:
            notes.append(f"Kapten aktif {active_name}: matchup sudah diperiksa; belum ada highlight material yang cukup untuk mengubah pilihan saat ini")
    else:
        captaincy = payload.get("captaincy") or {}
        model = captaincy.get("model") if isinstance(captaincy, dict) else None
        if isinstance(model, dict):
            captain = model.get("captain") if isinstance(model.get("captain"), dict) else {}
            vice = model.get("vice") if isinstance(model.get("vice"), dict) else {}
            cap_note = _first_highlight(captain)
            vice_note = _first_highlight(vice)
            if cap_note and captain.get("name"):
                notes.append(f"Kapten {captain.get('name')}: {cap_note}")
            elif vice_note and vice.get("name"):
                notes.append(f"Vice {vice.get('name')}: {vice_note}")
        else:
            comparison = captaincy.get("tactical_comparison") if isinstance(captaincy, dict) else None
            if isinstance(comparison, dict):
                cap = comparison.get("captain") if isinstance(comparison.get("captain"), dict) else {}
                highlights = cap.get("highlights") or []
                if highlights and captaincy.get("captain"):
                    notes.append(f"Kapten {captaincy.get('captain')}: {highlights[0]}")

    if notes:
        return " ".join(notes[:2])
    context = payload.get("tactical_context") or {}
    evidence = context.get("owned_evidence") or {}
    enough = int(evidence.get("cukup") or 0)
    limited = int(evidence.get("terbatas") or 0)
    return f"Matchup lawan sudah diperiksa untuk seluruh skuad; evidence cukup pada {enough} pemain dan masih terbatas pada {limited} pemain. Tidak ada klaim taktis yang dipaksakan saat evidence belum cukup."


def _compact_tactical_for_fast(raw: object) -> dict:
    row = raw if isinstance(raw, dict) else {}
    out = {
        "evidence_state": row.get("evidence_state"),
        "opponent_team_id": row.get("opponent_team_id"),
        "player_role": row.get("player_role"),
        "route_vulnerability_overlap": list(row.get("route_vulnerability_overlap") or [])[:1],
        "highlights": list(row.get("highlights") or [])[:1],
    }
    return {key: value for key, value in out.items() if value not in (None, [], {})}


def _compact_fast_transfer_battle(raw: object) -> dict:
    row = raw if isinstance(raw, dict) else {}
    edge = row.get("v3_edge") if isinstance(row.get("v3_edge"), dict) else {}
    predictor = row.get("predictor") if isinstance(row.get("predictor"), dict) else {}
    structural = row.get("structural_impact") if isinstance(row.get("structural_impact"), dict) else {}
    return {
        "owned": row.get("owned") or {},
        "challenger": row.get("challenger") or {},
        "v3_edge": {"3gw": edge.get("3gw") or {}, "5gw": edge.get("5gw") or {}},
        "xmins_start": row.get("xmins_start") or {},
        "official_price": row.get("official_price") or {},
        "official_ownership": row.get("official_ownership") or {},
        "predictor": {
            key: predictor.get(key)
            for key in ("direction", "urgency", "progress_percent", "predicted_player_change_eta", "evidence_state", "fresh", "imminent")
            if predictor.get(key) is not None
        },
        "structural_impact": {
            key: structural.get(key)
            for key in ("exact_sell_cost", "incoming_now_cost", "itb", "affordable", "switching_cost", "net_projected_gain")
            if structural.get(key) is not None
        },
        "risk": list(row.get("risk") or [])[:2],
        "confidence": row.get("confidence"),
        "decision": row.get("decision"),
        "reason": row.get("reason"),
        "flip_conditions": list(row.get("flip_conditions") or [])[:2],
        "evidence_ref": "data/dss_watchlist.json#owned_challenger_decision",
    }


def _compact_fast_comparator(raw: object) -> dict:
    row = raw if isinstance(raw, dict) else {}
    decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
    validation = row.get("publication_validation") if isinstance(row.get("publication_validation"), dict) else {}
    return {
        "status": row.get("status"),
        "contract": row.get("contract"),
        "owner": row.get("owner"),
        "capability_status": row.get("capability_status"),
        "owned_count": row.get("owned_count"),
        "governed_watchlist_count": row.get("governed_watchlist_count"),
        "material_candidate_count": row.get("material_candidate_count"),
        "mandatory_review_count": row.get("mandatory_review_count"),
        "comparison_count": row.get("comparison_count"),
        "decision": {
            "state": decision.get("state"),
            "execution_authorized": bool(decision.get("execution_authorized")),
            "reason": decision.get("reason"),
        },
        "main_transfer_battle_count": row.get("main_transfer_battle_count"),
        "publication_validation": {"status": validation.get("status")},
        "state_counts": row.get("state_counts") or {},
        "actionability_counts": row.get("actionability_counts") or {},
        "technical_evidence_ref": "data/dss_watchlist.json#owned_challenger_decision",
        "fast_surface_compacted": True,
    }


def _compact_fast_surface(payload: dict) -> dict:
    if not bool((payload.get("serving_contract") or {}).get("fast_context_compacted")):
        return payload

    for row in payload.get("owned_15") or []:
        if isinstance(row, dict):
            row["tactical_matchup"] = _compact_tactical_for_fast(row.get("tactical_matchup"))
    for rows in (payload.get("watchlist_20") or {}).values():
        for row in rows or []:
            if isinstance(row, dict):
                row["tactical_matchup"] = _compact_tactical_for_fast(row.get("tactical_matchup"))

    battle = payload.get("main_starting_xi_battle")
    if isinstance(battle, dict):
        for key in ("leader_metrics", "challenger_metrics"):
            metrics = battle.get(key)
            if isinstance(metrics, dict):
                metrics["tactical_matchup"] = _compact_tactical_for_fast(metrics.get("tactical_matchup"))

    captaincy = payload.get("captaincy")
    if isinstance(captaincy, dict):
        comparison = captaincy.get("tactical_comparison")
        if isinstance(comparison, dict):
            for key in ("captain", "vice"):
                comparison[key] = _compact_tactical_for_fast(comparison.get(key))

    payload["main_transfer_battles"] = [
        _compact_fast_transfer_battle(row)
        for row in (payload.get("main_transfer_battles") or [])[:3]
    ]
    payload["owned_vs_challenger"] = _compact_fast_comparator(payload.get("owned_vs_challenger"))
    payload.setdefault("serving_contract", {}).update({
        "fast_final_surface_compacted": True,
        "main_transfer_battles_visible": len(payload["main_transfer_battles"]),
        "full_transfer_evidence_ref": "data/dss_watchlist.json#owned_challenger_decision",
    })
    return payload


def _finalise_public_tactical(payload: dict, lineup: dict) -> dict:
    _sync_battle_outcome(payload, lineup)
    presentation = payload.get("user_presentation")
    if isinstance(presentation, dict):
        presentation["tactical_matchup"] = _tactical_presentation_note(payload)
    payload = _normalise_public_tactical_fields(payload)
    return _compact_fast_surface(payload)


def _validate_tactical(payload_name: str, payload: dict, expected_owned: int, expected_watch: int) -> None:
    context = payload.get("tactical_context") or {}
    assert int(context.get("owned_players") or 0) == expected_owned, (payload_name, context)
    assert int(context.get("watchlist_players") or 0) == expected_watch, (payload_name, context)
    usage = context.get("decision_usage") or {}
    assert usage.get("direct_xpts_mutation") is False, (payload_name, usage)
    owned_rows = ((payload.get("owned_squad") or {}).get("facts") or []) if "owned_squad" in payload else (payload.get("owned_15") or [])
    assert all(isinstance(row.get("tactical_matchup"), dict) for row in owned_rows), (payload_name, "owned tactical coverage")
    assert all((row.get("tactical_matchup") or {}).get("evidence_state") in {"CUKUP", "TERBATAS", "TIDAK_TERSEDIA"} for row in owned_rows), (payload_name, "owned tactical state")
    watch_positions = ((payload.get("external_watchlist") or {}).get("positions") or {}) if "external_watchlist" in payload else (payload.get("watchlist_20") or {})
    watch_rows = [row for rows in watch_positions.values() for row in rows]
    assert len(watch_rows) == expected_watch, (payload_name, len(watch_rows))
    assert all(isinstance(row.get("tactical_matchup"), dict) for row in watch_rows), (payload_name, "watch tactical coverage")
    assert "verified_shape" not in json.dumps(payload, ensure_ascii=False), (payload_name, "misleading verified_shape alias leaked")
    presentation = payload.get("user_presentation") or {}
    tactical_text = str(presentation.get("tactical_matchup") or "")
    assert tactical_text, (payload_name, "missing tactical user presentation")
    authority, active_captain = _authority_captain(payload)
    active_name = str(active_captain.get("name") or "")
    if authority == "USER_OVERRIDE" and active_name:
        assert f"Kapten aktif {active_name}:" in tactical_text, (payload_name, "tactical presentation ignored user captain authority", tactical_text)
        model = (payload.get("captaincy") or {}).get("model") if isinstance(payload.get("captaincy"), dict) else None
        model_captain = model.get("captain") if isinstance(model, dict) and isinstance(model.get("captain"), dict) else {}
        model_name = str(model_captain.get("name") or "")
        if model_name and model_name != active_name:
            assert f"Kapten {model_name}:" not in tactical_text, (payload_name, "engine captain mislabeled as active captain", tactical_text)


def run() -> dict:
    tactical_overlay = apply_report_overlay()
    lineup = _load(DATA / "lineup_decision.json")
    for name in ("user_report.json", "decision_brief.json", "deep_review_payload.json"):
        path = DATA / name
        payload = _load(path)
        atomic_json(path, _finalise_public_tactical(payload, lineup))

    registry = _load(REGISTRY)
    runtime_registry = _load(DATA / "report_artifact_registry.json")
    assert runtime_registry == registry
    contract = registry["consumer_contract"]
    expected_owned = int(contract["owned_count"])
    expected_watch = int(contract["watchlist_total"])
    expected_per = int(contract["watchlist_per_position"])
    positions = list(contract["watchlist_positions"])

    brief = _load(DATA / "decision_brief.json")
    deep = _load(DATA / "deep_review_payload.json")
    user = _load(DATA / "user_report.json")
    summary = _load(DATA / "dss_watchlist_summary.json")
    latest = _load(DATA / "latest.json")
    team = _load(DATA / "team.json")
    canonical_watch = _load(DATA / "dss_watchlist.json")

    ledger_rows = [row for row in team.get("team_value_ledger") or [] if isinstance(row, dict)]
    resolved_squad_rows = [row for row in team.get("squad") or [] if isinstance(row, dict)]
    authoritative_owned_ids = _element_ids(ledger_rows)
    resolved_squad_ids = _element_ids(resolved_squad_rows)
    assert len(ledger_rows) == expected_owned and len(authoritative_owned_ids) == expected_owned, (
        "team_value_ledger",
        len(ledger_rows),
        len(authoritative_owned_ids),
    )
    assert len(resolved_squad_rows) == expected_owned and resolved_squad_ids == authoritative_owned_ids, (
        "resolved_team_squad_drift",
        sorted(resolved_squad_ids - authoritative_owned_ids),
        sorted(authoritative_owned_ids - resolved_squad_ids),
    )

    owned_surfaces = (
        ("brief", brief.get("owned_15") or []),
        ("deep", deep.get("owned_15") or []),
        ("user", ((user.get("owned_squad") or {}).get("facts") or [])),
    )
    for payload_name, rows in owned_surfaces:
        _validate_owned_transparency(payload_name, rows, expected_owned, contract)
        ids = _element_ids(rows)
        assert ids == authoritative_owned_ids, (
            payload_name,
            "owned_membership_drift",
            sorted(ids - authoritative_owned_ids),
            sorted(authoritative_owned_ids - ids),
        )
    owned_ids = authoritative_owned_ids

    canonical_watch_positions = canonical_watch.get("positions") or {}
    assert set(canonical_watch_positions) == set(positions), ("canonical_watchlist", sorted(canonical_watch_positions))
    canonical_watch_sets = _watch_ids_by_position(canonical_watch_positions, positions)
    for position in positions:
        canonical_rows = canonical_watch_positions.get(position) or []
        assert len(canonical_rows) == expected_per, ("canonical_watchlist", position, len(canonical_rows), expected_per)
        assert len(canonical_watch_sets[position]) == expected_per, ("canonical_watchlist", position, "duplicate_membership")
        assert not (owned_ids & canonical_watch_sets[position]), (
            "canonical_watchlist",
            position,
            sorted(owned_ids & canonical_watch_sets[position]),
        )

    for payload_name, watch_positions in (
        ("brief", brief.get("watchlist_20") or {}),
        ("deep", deep.get("watchlist_20") or {}),
        ("user", ((user.get("external_watchlist") or {}).get("positions") or {})),
        ("summary", summary.get("positions") or {}),
    ):
        assert set(watch_positions) == set(positions), (payload_name, sorted(watch_positions))
        surface_sets = _watch_ids_by_position(watch_positions, positions)
        for position in positions:
            rows = watch_positions.get(position) or []
            assert len(rows) == expected_per, (payload_name, position, len(rows), expected_per)
            assert all(row.get("position") == position for row in rows), (payload_name, position)
            assert surface_sets[position] == canonical_watch_sets[position], (
                payload_name,
                position,
                "watchlist_membership_drift",
                sorted(surface_sets[position] - canonical_watch_sets[position]),
                sorted(canonical_watch_sets[position] - surface_sets[position]),
            )
        ids = _watch_ids(watch_positions)
        assert len(ids) == expected_watch and len(set(ids)) == expected_watch, (payload_name, len(ids), len(set(ids)))
        assert not (owned_ids & set(ids)), (payload_name, sorted(owned_ids & set(ids)))

    lineup_squad_ids = _element_ids([row for row in lineup.get("squad_rows") or [] if isinstance(row, dict)])
    xi_ids = _element_ids([row for row in lineup.get("starting_xi") or [] if isinstance(row, dict)])
    comparison = list(lineup.get("formation_comparison") or [])
    selected_rows = [row for row in comparison if row.get("selected") is True]
    lineup_score = lineup.get("lineup_score") or {}
    lineup_governance = lineup.get("governance") or {}
    assert lineup_squad_ids == authoritative_owned_ids, (
        "lineup_authority_drift",
        sorted(lineup_squad_ids - authoritative_owned_ids),
        sorted(authoritative_owned_ids - lineup_squad_ids),
    )
    assert len(xi_ids) == 11 and xi_ids <= authoritative_owned_ids, ("lineup_xi_membership", sorted(xi_ids))
    assert len(selected_rows) == 1, ("formation_comparison_selected_count", len(selected_rows))
    assert selected_rows[0].get("formation") == lineup.get("formation"), (
        "formation_comparison_final_drift",
        selected_rows[0].get("formation"),
        lineup.get("formation"),
    )
    assert lineup_score.get("base_robust") is not None, "lineup_score.base_robust missing after tactical overlay"
    assert isinstance(lineup_score.get("risk_adjustment"), dict), "lineup_score.risk_adjustment missing after tactical overlay"
    assert lineup_governance.get("team_state_authority_consumed") is True, "lineup bypassed team-state authority"
    assert lineup_governance.get("legacy_lock_fixture_fallback") is False, "production lineup used legacy raw-lock fallback"
    assert lineup_governance.get("tactical_overlay_preserves_decision_transparency") is True
    assert lineup_governance.get("formation_comparison_reconciled_to_final_xi") is True

    latest_lineup = latest.get("lineup_decision_summary") or {}
    assert latest_lineup.get("formation") == lineup.get("formation"), (
        "latest_lineup_formation_drift",
        latest_lineup.get("formation"),
        lineup.get("formation"),
    )
    assert latest_lineup.get("captain") == (lineup.get("captain") or {}).get("name"), "latest captain drift"
    assert latest_lineup.get("vice_captain") == (lineup.get("vice_captain") or {}).get("name"), "latest vice drift"
    assert latest_lineup.get("risk_adjustment") == lineup_score.get("risk_adjustment"), "latest lineup risk-adjustment drift"
    assert int(latest_lineup.get("bench_close_battles") or 0) == len(((lineup.get("bench") or {}).get("close_battles") or [])), "latest bench battle drift"

    for payload in (user, brief):
        assert (payload.get("serving_contract") or {}).get("owned") == expected_owned
        assert (payload.get("serving_contract") or {}).get("watchlist") == expected_watch

    assert (brief.get("serving_contract") or {}).get("fast_final_surface_compacted") is True
    assert int((brief.get("serving_contract") or {}).get("main_transfer_battles_visible") or 0) <= 3
    assert (brief.get("owned_vs_challenger") or {}).get("fast_surface_compacted") is True
    assert (brief.get("owned_vs_challenger") or {}).get("technical_evidence_ref") == "data/dss_watchlist.json#owned_challenger_decision"

    for payload_name, payload in (("brief", brief), ("deep", deep), ("user", user)):
        _validate_tactical(payload_name, payload, expected_owned, expected_watch)
        if contract.get("report_time_intelligence_required") is True:
            report_time = payload.get("report_time_intelligence") or {}
            assert report_time.get("status") in {"REFRESH_REQUIRED", "READY", "INVALID_EVIDENCE_CONTRACT"}, (payload_name, report_time)
            assert "pundit_consensus_vs_dss" in report_time, payload_name
            assert "fixture_strategy" in report_time, payload_name
            assert "community_signal" in report_time, payload_name
        if contract.get("model_validation_required") is True:
            validation = payload.get("model_validation") or {}
            assert (validation.get("confidence_calibration") or {}).get("state") in {"EARLY_SEASON_CONSERVATIVE", "CALIBRATION_REVIEW_REQUIRED", "CONFIDENCE_RANGE_PRESENT"}, payload_name
            settled = validation.get("settled_prediction") or {}
            assert "sample_size" in settled and "status" in settled, payload_name
        if contract.get("weather_context_required") is True:
            weather = payload.get("weather_context") or {}
            assert weather.get("status") in {"AVAILABLE", "NO_FORECAST_IN_WINDOW"}, (payload_name, weather)
            assert weather.get("advisory_only") is True, payload_name
            assert weather.get("causality_guard"), payload_name
        if contract.get("personal_gameweek_context_required") is True:
            _validate_personal_gameweek_context(payload_name, payload)
    assert deep.get("payload_type") == "DEEP_REVIEW_PAYLOAD_V2"

    files = latest.get("files") or {}
    assert files.get("decision_brief") == "data/decision_brief.json"
    assert files.get("deep_review_payload") == "data/deep_review_payload.json"
    assert files.get("dss_watchlist_summary") == "data/dss_watchlist_summary.json"
    assert files.get("report_artifact_registry") == "data/report_artifact_registry.json"
    assert latest.get("report_serving", {}).get("owned_count") == expected_owned
    assert latest.get("report_serving", {}).get("watchlist_count") == expected_watch
    assert latest.get("report_serving", {}).get("personal_gameweek_context") is True
    assert latest.get("report_serving", {}).get("report_time_intelligence") is True
    assert latest.get("report_serving", {}).get("technical_lazy_load") is True
    assert latest.get("report_serving", {}).get("fast_context_compacted") is True
    assert latest.get("report_serving", {}).get("deep_context_full_fidelity") is True

    sizes = {}
    for name, spec in (registry.get("artifacts") or {}).items():
        path_text = str(spec.get("path") or "")
        if not path_text.startswith("data/"):
            continue
        path = DATA / path_text.removeprefix("data/")
        if not path.exists():
            continue
        sizes[name] = path.stat().st_size
        if spec.get("priority") == "P0" and spec.get("max_bytes") is not None:
            assert sizes[name] <= int(spec["max_bytes"]), (name, sizes[name], spec["max_bytes"])

    result = {
        "status": "PASS",
        "registry": registry.get("registry"),
        "owned": expected_owned,
        "watchlist": expected_watch,
        "per_position": expected_per,
        "owned_transparency": True,
        "authoritative_owned_reconciled": True,
        "watchlist_membership_reconciled": True,
        "lineup_metadata_reconciled": True,
        "latest_lineup_summary_reconciled": True,
        "tactical_context": True,
        "tactical_presentation": True,
        "tactical_authority_aligned": True,
        "tactical_overlay": tactical_overlay,
        "tactical_direct_xpts_mutation": False,
        "selection_score": contract.get("owned_rows_require_selection_score"),
        "model_validation": contract.get("model_validation_required"),
        "weather_context": contract.get("weather_context_required"),
        "report_time_intelligence": contract.get("report_time_intelligence_required"),
        "personal_gameweek_context": contract.get("personal_gameweek_context_required"),
        "fast_context_compacted": True,
        "fast_final_surface_compacted": True,
        "deep_context_full_fidelity": True,
        "sizes": sizes,
        "default_fast": latest.get("report_serving", {}).get("default_fast_review_artifact") or latest.get("report_serving", {}).get("default_fast_artifact"),
        "default_deep": latest.get("report_serving", {}).get("default_deep_review_artifact"),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    run()
