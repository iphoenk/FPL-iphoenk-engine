from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.engines import report_architecture as r
from src.engines import report_materializer
from src.engines.report_time_intelligence import build_pundit_consensus, validate_evidence, validate_registry
from src.engines.report_transparency_overlay import _confidence_calibration, _decorate_owned
from src.sources.weather_open_meteo import _resolve_venue, _severity
from src.utils import ROOT as UTILS_ROOT

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc)


def _projection(element, name, *, mean=6.0, std=2.0, start=0.92, dnp=0.03, xmins=82.0, role=False):
    row = {
        "element": element,
        "name": name,
        "position": "MID",
        "projection_confidence": "HIGH",
        "xmins": {
            "start_probability": start,
            "bench_probability": max(0.0, 1.0 - start - dnp),
            "dnp_probability": dnp,
            "expected_minutes": xmins,
        },
        "xpts_by_gw": [{"gw": 2, "mean": mean, "std": std, "fixtures": [{"event": 2}]}],
    }
    if role:
        row["penalty_role"] = "first_choice"
    return row


def test_captain_ranking_is_not_auto_lock_without_role_evidence():
    lineup = {
        "planning_gw": 2,
        "captain": {"element": 1},
        "vice_captain": {"element": 2},
        "captain_safe_pool": [{"element": 1, "captain_score": 6.2}, {"element": 2, "captain_score": 5.0}],
    }
    projections = {"planning_gw": 2, "players": [_projection(1, "A"), _projection(2, "B", mean=5.0)]}
    out = r._captaincy_section(lineup, projections)
    assert out["decision"] != "LOCK"
    assert out["model"]["checks"]["role_evidence"] is False


def test_captain_can_lock_when_strict_evidence_passes():
    lineup = {
        "planning_gw": 2,
        "captain": {"element": 1},
        "vice_captain": {"element": 2},
        "captain_safe_pool": [{"element": 1, "captain_score": 6.5}, {"element": 2, "captain_score": 5.0}],
    }
    projections = {"planning_gw": 2, "players": [_projection(1, "A", role=True), _projection(2, "B", mean=5.0, role=True)]}
    out = r._captaincy_section(lineup, projections)
    assert out["decision"] == "LOCK"
    assert out["confidence"] == "HIGH"


def test_lineup_battle_remains_open_when_margin_is_close():
    lineup = {
        "formation": "3-4-3",
        "starting_xi": [],
        "main_starting_xi_battle": {
            "status": "CLOSE",
            "margin": 0.13,
            "starter_side": [{"name": "A"}],
            "bench_side": [{"name": "B"}],
            "alternative_formation": "4-4-2",
        },
    }
    out = r._lineup_section(lineup, {"initial_report": False, "changed": []}, True)
    assert out["decision"] == "OPEN"
    assert out["model"]["confidence"] == "LOW"
    assert out["model"]["battle"]["starter"] == "A"
    assert out["model"]["battle"]["challenger"] == "B"


def test_price_radar_filters_external_market_noise_until_full_dss_watchlist():
    alerts = {
        "alerts": [
            {"element": 1, "name": "Owned", "owned": True, "risk_direction": "FALL", "urgency": "CRITICAL", "official_progress_pct": -95, "official_projection_health": "SUSPECT_STATIC_OFFSET0"},
            {"element": 2, "name": "External", "owned": False, "risk_direction": "RISE", "urgency": "CRITICAL", "official_progress_pct": 98},
        ]
    }
    team = {"team_value_ledger": [{"element": 1}]}
    out = r._price_section(alerts, team, {})
    assert [x["name"] for x in out["owned"]] == ["Owned"]
    assert out["external_watchlist"] == []
    assert out["external_status"] == "INSUFFICIENT_EVIDENCE"
    assert "SUSPECT_STATIC_OFFSET0" not in json.dumps(out)


def test_watchlist_refuses_ranking_without_full_dss_contract():
    out = r._watchlist_section({"positions": {"MID": [{"element": 99, "name": "Haul"}]}})
    assert out["status"] == "INSUFFICIENT_EVIDENCE"
    assert out["positions"]["MID"] == []


def test_stable_delta_is_compact_and_action_board_is_bounded():
    current = {
        "squad": "HOLD",
        "starting_xi": [1, 2],
        "formation": "3-4-3",
        "captain": 1,
        "vice_captain": 2,
        "chip": None,
        "price": [],
        "critical_health": {"overall": "GREEN", "critical_failed": [], "prediction_quality": "HEALTHY"},
    }
    delta = r._changes(current, {"state": current})
    assert delta["material_change"] is False
    user = {
        "decision": {"squad": "HOLD"},
        "starting_xi": {"decision": "OPEN", "model": {"battle": {"starter": "A", "challenger": "B"}}},
        "captaincy": {"decision": "OPEN", "facts": {"model_candidate": "C"}, "reason": "need evidence"},
        "chip": {"decision": "HOLD"},
        "price_radar": {"owned": [{"name": f"P{i}", "action": "HOLD", "direction": "RISE", "urgency": "HIGH"} for i in range(20)]},
        "external_watchlist": {"status": "INSUFFICIENT_EVIDENCE"},
    }
    assert len(r._action_board(user)) <= 8


def test_report_artifact_registry_requires_15_owned_and_20_watchlist():
    registry = report_materializer.load_registry()
    contract = registry["consumer_contract"]
    assert contract["owned_count"] == 15
    assert contract["watchlist_total"] == 20
    assert contract["watchlist_per_position"] == 5
    assert contract["watchlist_positions"] == ["GK", "DEF", "MID", "FWD"]
    assert registry["governance"]["report_materializer_may_reduce_fields_but_may_not_make_new_football_decisions"] is True


def test_watchlist_summary_is_exactly_5_per_position_and_excludes_owned(monkeypatch, tmp_path):
    monkeypatch.setattr(report_materializer, "DATA", tmp_path)
    owned = [{"element": i} for i in range(1, 16)]
    (tmp_path / "team.json").write_text(json.dumps({"team_value_ledger": owned}), encoding="utf-8")
    positions = {}
    element = 100
    for pos in ("GK", "DEF", "MID", "FWD"):
        rows = []
        for rank in range(1, 6):
            element += 1
            rows.append({
                "element": element,
                "rank": rank,
                "lifecycle": "NEW",
                "name": f"{pos} {rank}",
                "team": "X",
                "position": pos,
                "price": 5.0,
                "projection_confidence": "MEDIUM",
                "xmins": {"expected_minutes": 75, "start_probability": 0.85},
                "horizons": {"3": {"mean": 10}, "5": {"mean": 16}, "10": {"mean": 31}, "15": {"mean": 45}},
                "reasons": ["starter security / xMins kuat"],
                "risks": ["role belum penuh"],
                "price_risk": {"risk_direction": "RISE", "urgency": "LOW", "official_progress_pct": 10},
                "action": "WATCH",
            })
        positions[pos] = rows
    summary = report_materializer._watchlist_summary({"status": "READY", "screening_contract": "FULL_DSS_SCREEN_V1", "positions": positions})
    assert summary["count"] == 20
    assert summary["per_position"] == 5
    assert all(len(summary["positions"][p]) == 5 for p in positions)
    assert not ({x["element"] for x in owned} & {x["element"] for rows in summary["positions"].values() for x in rows})


def test_finance_uses_current_totals_not_purchase_baseline():
    finance = report_materializer._finance({"totals": {"market_value": 997, "sell_value": 995, "itb": 5}, "team_value_ledger": []})
    assert finance == {
        "squad_market_value": 99.7,
        "itb": 0.5,
        "total_team_value": 100.2,
        "squad_sell_value": 99.5,
        "spendable_value": 100.0,
    }


def _signal(source_id: str, source_class: str, subject: str, stance: str, *, hours_ago: int = 1, topic: str = "transfer") -> dict:
    observed = datetime(2026, 8, 26, 23 - hours_ago + 1, 0, tzinfo=timezone.utc)
    return {
        "source_id": source_id,
        "source_class": source_class,
        "topic": topic,
        "subject": subject,
        "stance": stance,
        "observed_at": observed.isoformat(),
        "source_url": f"https://example.com/{source_id}",
        "summary": f"{source_id} {stance} {subject}",
    }


def test_report_time_registry_has_separated_source_classes():
    health = validate_registry()
    assert health["integrity_ok"] is True
    registry = (UTILS_ROOT / "config" / "sources" / "report_time_registry.json").read_text()
    assert '"onefpl"' in registry
    assert '"ben_crellin"' in registry
    assert '"reddit_fantasypl"' in registry
    assert '"PUNDIT_CONSENSUS"' in registry
    assert '"FIXTURE_STRATEGY_EXPERT"' in registry
    assert '"COMMUNITY_SIGNAL"' in registry


def test_pundit_consensus_aligns_with_dss_watchlist():
    payload = {
        "contract": "report_time_evidence_v1",
        "signals": [
            _signal("fpl_harry", "PUNDIT_CONSENSUS", "Example Player", "BUY"),
            _signal("fpl_focal", "PUNDIT_CONSENSUS", "Example Player", "BUY"),
            _signal("lets_talk_fpl", "PUNDIT_CONSENSUS", "Example Player", "BUY"),
        ],
    }
    validated = validate_evidence(payload, now=NOW)
    rows = build_pundit_consensus(
        validated["accepted"],
        {"exampleplayer": {"state": "WATCHLIST", "element": 999}},
        json.loads((UTILS_ROOT / "config" / "sources" / "report_time_registry.json").read_text()),
    )
    assert len(rows) == 1
    assert rows[0]["winner"] == "BUY"
    assert rows[0]["strength"] == "STRONG"
    assert rows[0]["alignment_with_dss"] == "ALIGN"
    assert rows[0]["dss_state"] == "WATCHLIST"


def test_pundit_consensus_surfaces_divergence_instead_of_mutating_dss():
    payload = {"contract": "report_time_evidence_v1", "signals": [_signal("fpl_harry", "PUNDIT_CONSENSUS", "Outside Player", "BUY"), _signal("fpl_focal", "PUNDIT_CONSENSUS", "Outside Player", "BUY")]}
    validated = validate_evidence(payload, now=NOW)
    registry = json.loads((UTILS_ROOT / "config" / "sources" / "report_time_registry.json").read_text())
    rows = build_pundit_consensus(validated["accepted"], {}, registry)
    assert rows[0]["alignment_with_dss"] == "DIVERGE"
    assert rows[0]["advisory_only"] is True


def test_ben_crellin_and_reddit_do_not_vote_in_pundit_consensus():
    payload = {
        "contract": "report_time_evidence_v1",
        "signals": [
            _signal("ben_crellin", "FIXTURE_STRATEGY_EXPERT", "GW8", "FIXTURE_ALERT", topic="fixtures"),
            _signal("reddit_fantasypl", "COMMUNITY_SIGNAL", "Example Player", "ROLE_POSITIVE", topic="role"),
            _signal("fpl_harry", "PUNDIT_CONSENSUS", "Example Player", "BUY"),
        ],
    }
    validated = validate_evidence(payload, now=NOW)
    registry = json.loads((UTILS_ROOT / "config" / "sources" / "report_time_registry.json").read_text())
    assert build_pundit_consensus(validated["accepted"], {}, registry) == []
    by_source = {row["source_id"]: row for row in validated["accepted"]}
    assert by_source["ben_crellin"]["consensus_eligible"] is False
    assert by_source["reddit_fantasypl"]["consensus_eligible"] is False


def test_stale_pundit_signal_is_not_counted_as_current_consensus():
    payload = {
        "contract": "report_time_evidence_v1",
        "signals": [
            {**_signal("fpl_harry", "PUNDIT_CONSENSUS", "Example Player", "BUY"), "observed_at": "2026-08-20T00:00:00+00:00"},
            _signal("fpl_focal", "PUNDIT_CONSENSUS", "Example Player", "BUY"),
        ],
    }
    validated = validate_evidence(payload, now=NOW)
    registry = json.loads((UTILS_ROOT / "config" / "sources" / "report_time_registry.json").read_text())
    assert build_pundit_consensus(validated["accepted"], {}, registry) == []


def test_report_time_evidence_rejects_source_class_mismatch():
    payload = {"contract": "report_time_evidence_v1", "signals": [_signal("ben_crellin", "PUNDIT_CONSENSUS", "GW8", "BUY")]}
    result = validate_evidence(payload, now=NOW)
    assert result["accepted_count"] == 0
    assert result["rejected"][0]["reason"] == "SOURCE_CLASS_MISMATCH"


def _load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_weather_acquisition_is_optional_enrichment_and_context_is_governed_capability():
    sources = _load("config/sources/registry.json")
    registry = _load("config/v3_service_registry.json")
    services = registry["services"]
    source_map = {row["id"]: row for row in sources["sources"]}
    weather = source_map["open_meteo"]
    assert weather["class"] == "ENRICHMENT"
    assert weather["critical"] is False
    assert weather["adapter"] == "weather_artifact"
    assert registry["policy"]["weather_acquisition_lives_inside_source_layer"] is True
    assert registry["policy"]["weather_context_is_separate_governed_enrichment_capability"] is True
    assert "weather_context" in services
    source_layer = services["source_layer"]
    context = services["weather_context"]
    assert source_layer["commands"] == [{"module": "src.engines.source_layer", "args": []}]
    assert "official_snapshot.json" in source_layer["inputs"]
    assert "fixture_weather.json" in source_layer["artifacts"]
    assert context["commands"] == [{"module": "src.engines.weather_context", "args": []}]
    assert "fixture_weather.json" in context["inputs"]
    assert "weather_context.json" in context["artifacts"]
    assert "weather_context_health.json" in context["artifacts"]


def test_weather_policy_cannot_directly_mutate_decisions():
    cfg = _load("config/intelligence/weather_context.json")
    governance = cfg["governance"]
    assert governance["advisory_only"] is True
    for key in ("may_directly_change_xpts", "may_directly_change_captaincy", "may_directly_change_starting_xi", "may_directly_change_transfer_decision", "may_directly_change_watchlist_membership"):
        assert governance[key] is False
    assert governance["rain_probability_is_not_rain_intensity"] is True
    assert governance["post_match_attribution_label"] == "POSSIBLE_CONTRIBUTING_FACTOR"


def test_weather_severity_uses_intensity_and_gusts_from_config():
    cfg = _load("config/intelligence/weather_context.json")
    label, signals = _severity({"temperature_c": 14, "precipitation_probability_pct": 90, "precipitation_mm_h": 0.0, "wind_speed_kmh": 12, "wind_gust_kmh": 46}, cfg)
    assert label == "ADVERSE"
    assert "wind_gust" in signals
    assert "precipitation_intensity" not in signals


def test_venue_registry_has_current_unique_pl_coverage():
    registry = _load("config/venues/premier_league_2026_27.json")
    venues = registry["venues"]
    names = [row["team_name"] for row in venues]
    ids = [int(row["team_id"]) for row in venues]
    assert registry["schema_version"] == 2
    assert len(venues) == 20
    assert len(set(names)) == 20
    assert sorted(ids) == list(range(1, 21))
    assert {"Coventry City", "Hull City", "Ipswich Town"}.issubset(set(names))
    assert not ({"Burnley", "West Ham", "Wolves"} & set(names))
    assert all(-90 <= float(row["latitude"]) <= 90 for row in venues)
    assert all(-180 <= float(row["longitude"]) <= 180 for row in venues)


def test_venue_identity_mismatch_fails_soft_instead_of_using_stale_stadium():
    by_id = {7: {"team_id": 7, "team_name": "Old Team", "venue": "Wrong Stadium"}}
    by_name = {"Coventry City": {"team_id": 99, "team_name": "Coventry City", "venue": "Wrong Stadium"}}
    venue, state = _resolve_venue(7, "Coventry City", by_id, by_name)
    assert venue is None
    assert state == "VENUE_IDENTITY_MISMATCH"


def _owned_rows(confidence="MEDIUM"):
    return [{"element": idx + 1, "model_confidence": confidence} for idx in range(15)]


def test_projection_confidence_guard_is_early_season_conservative_before_gw5():
    state = _confidence_calibration(_owned_rows("MEDIUM"), 2)
    assert state["state"] == "EARLY_SEASON_CONSERVATIVE"
    assert state["counts"]["HIGH"] == 0


def test_projection_confidence_guard_requires_review_from_gw5_if_no_high():
    state = _confidence_calibration(_owned_rows("MEDIUM"), 5)
    assert state["state"] == "CALIBRATION_REVIEW_REQUIRED"


def test_owned_transparency_exposes_selection_score_and_close_gk_choice():
    owned = [{"element": idx, "name": f"P{idx}", "model_confidence": "MEDIUM"} for idx in range(1, 16)]
    projections = {"players": [{"element": idx, "xpts_by_gw": [{"gw": 2, "mean": 3.0 + idx / 10.0, "std": 1.5}]} for idx in range(1, 16)]}
    squad_rows = [{"element": idx, "position": "GK" if idx <= 2 else "DEF", "selection_score": 4.0 - idx / 10.0} for idx in range(1, 16)]
    lineup = {
        "squad_rows": squad_rows,
        "starting_xi": [{"element": 1}, *[{"element": idx} for idx in range(3, 13)]],
        "main_starting_xi_battle": {"status": "CLEAR", "starter_side": [], "bench_side": []},
    }
    rows = _decorate_owned(owned, projections, lineup, 2)
    by_id = {int(row["element"]): row for row in rows}
    assert all(row.get("selection_score") is not None for row in rows)
    assert by_id[1]["choice_state"] == "OPEN"
    assert by_id[2]["choice_state"] == "OPEN"
    assert by_id[1]["lineup_status"] == "START"
    assert by_id[2]["lineup_status"] == "BENCH"


def test_report_contract_requires_xpts_selection_weather_and_settled_validation():
    report = _load("config/report_artifact_registry.json")
    contract = report["consumer_contract"]
    assert report["registry"] == "REPORT_ARTIFACT_REGISTRY_V3"
    assert contract["owned_rows_require_current_gw_xpts"] is True
    assert contract["owned_rows_require_selection_score"] is True
    assert contract["owned_rows_require_lineup_status"] is True
    assert contract["owned_rows_require_choice_state"] is True
    assert contract["model_validation_required"] is True
    assert contract["weather_context_required"] is True


def test_report_materializer_runs_transparency_before_serving_validation():
    services = _load("config/v3_service_registry.json")
    commands = [row["module"] for row in services["services"]["report_materializer"]["commands"]]
    assert commands == ["src.engines.report_materializer", "src.engines.report_transparency_overlay", "src.engines.report_serving_validate"]
