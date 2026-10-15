from __future__ import annotations

from copy import deepcopy

from src.engines.v12_gw1_gw6_history_context import build_retrospective_context

SLOT = "2026-10-13T19:45:00+07:00"
BOOTSTRAP = {"elements": [
    {"id": 154, "web_name": "Palmer", "team": 6, "element_type": 3},
    {"id": 40, "web_name": "Rogers", "team": 6, "element_type": 3},
    {"id": 165, "web_name": "João Pedro", "team": 6, "element_type": 4},
    {"id": 411, "web_name": "Haaland", "team": 15, "element_type": 4},
]}
FPL_FIXTURES = [
    {"id": 53, "event": 6, "team_h": 6, "team_a": 3,
     "finished": False, "finished_provisional": True}
]
HISTORY = {
    "coverage_gate": {"status": "PARTIAL", "all_historical_gws_finalized": False},
    "players": {
        "154": {"history": {
            "1": {"status": "FINAL", "aggregate": {"minutes": 90, "goals_scored": 1, "total_points": 8}, "fixture_count": 1},
            "6": {"status": "PENDING", "aggregate": {"minutes": 85, "assists": 2, "total_points": 10}, "fixture_count": 1},
        }},
    },
}
UNDERSTAT = {
    "source_health": "GREEN",
    "normalization_status": "NORMALIZED",
    "effective_at": "2026-10-13T12:31:00+00:00",
    "record_groups": {
        "players": [
            {"source_native_id": 8497, "official_element_id": 154,
             "identity_status": "VERIFIED_MANUAL", "games": 6,
             "time": 535, "goals": 2, "assists": 3, "xg": 1.82, "xa": 2.20},
            {"source_native_id": 99999, "official_element_id": 165,
             "identity_status": "ACTIONABLE_UNMAPPED", "games": 5, "time": 400, "xg": 6},
        ]
    },
}
FOTMOB = {
    "source_health": "GREEN",
    "normalization_status": "NORMALIZED",
    "effective_at": "2026-10-13T12:31:00+00:00",
    "record_groups": {
        "teams": [
            {"source_native_id": 8455, "official_team_id": 6,
             "identity_status": "VERIFIED_MANUAL"},
            {"source_native_id": 8678, "official_team_id": 3,
             "identity_status": "VERIFIED_MANUAL"},
        ],
        "fixtures": [
            {"source_native_id": 5795467, "official_fixture_id": 53,
             "round": "6", "identity_status": "VERIFIED_MANUAL",
             "home": {"source_native_id": 8455, "name": "Chelsea"},
             "away": {"source_native_id": 8678, "name": "Bournemouth"},
             "status": {"finished": True, "scoreStr": "5 - 1"}},
        ],
    },
}
OBSERVATION = {
    "evidence_state": "OBSERVED", "fixture_id": 53,
    "team_id": 6, "gw": 6, "formation": "3-4-2-1",
    "manager": "Xabi Alonso",
    "observed_at": "2026-10-13T12:35:00+00:00",
    "reference_url": "https://www.premierleague.com/en/clubs/8/chelsea",
    "player_roles": {"154": "behind_striker", "40": "behind_striker"},
}


def build(**changes):
    kwargs = {
        "bootstrap": BOOTSTRAP,
        "official_fixtures": FPL_FIXTURES,
        "full_history": HISTORY,
        "understat": UNDERSTAT,
        "fotmob": FOTMOB,
        "report_slot": SLOT,
        "tactical_observation": OBSERVATION,
    }
    kwargs.update(changes)
    return build_retrospective_context(**kwargs)


def test_provisional_fpl_gw6_never_promoted_by_fotmob_ft():
    ctx = build()
    assert ctx["official_status"] == "PARTIAL"
    assert ctx["official_points_finalized"] is False
    assert ctx["focus_team"]["form_gw1_gw6"]["matches"][0]["result"] == "W"
    assert ctx["focus_team"]["form_gw1_gw6"]["matches"][0]["fpl_points_settlement"] == "PENDING"
    palmer = next(x for x in ctx["players"] if x["official_element_id"] == 154)
    assert palmer["finalized_only_totals"]["total_points"] == 8
    assert palmer["historical_gws"][5]["official_status"] == "PENDING"
    assert ctx["effect_on_fpl_finality"] == "NONE"
    assert ctx["effect_on_projection"] == "NONE_ADVISORY_ONLY"


def test_understat_joins_only_verified_source_native_identity_and_season_scope():
    ctx = build()
    palmer = next(x for x in ctx["players"] if x["official_element_id"] == 154)
    pedro = next(x for x in ctx["players"] if x["official_element_id"] == 165)
    assert palmer["provider_skill_observation"]["metrics"]["xgi"] == 4.02
    assert palmer["provider_skill_observation"]["season_aggregate_only"] is True
    assert pedro["provider_skill_observation"]["status"] == "UNAVAILABLE"
    assert ctx["source_health"]["understat"]["verified_join_count"] == 1
    assert ctx["source_health"]["understat"]["unmapped_provider_count"] == 1
    assert len(ctx["players"]) == 4
    assert ctx["expected_official_gw_slots"] == 24


def test_future_source_and_future_coach_observation_excluded():
    ctx = build(report_slot="2026-10-13T09:00:00+07:00")
    assert ctx["source_health"]["understat"]["status"] == "UNAVAILABLE"
    assert ctx["source_health"]["fotmob"]["status"] == "UNAVAILABLE"
    assert ctx["focus_team"]["tactical_observation"]["status"] == "UNAVAILABLE"


def test_mismatched_official_fixture_or_duplicate_provider_rows_fail_closed():
    wrong = deepcopy(FPL_FIXTURES)
    wrong[0]["team_h"] = 99
    ctx = build(official_fixtures=wrong)
    assert ctx["source_health"]["fotmob"]["verified_match_count"] == 0
    assert ctx["focus_team"]["tactical_observation"]["status"] == "UNAVAILABLE"
    duplicates = deepcopy(FOTMOB)
    duplicates["record_groups"]["fixtures"].append(deepcopy(duplicates["record_groups"]["fixtures"][0]))
    dup = build(fotmob=duplicates)
    assert dup["source_health"]["fotmob"]["rejected_or_ambiguous"] >= 1


def test_context_keeps_coach_fit_and_formation_fit_uncalibrated():
    ctx = build()
    observed = ctx["focus_team"]["tactical_observation"]
    assert observed["status"] == "MATCH_SPECIFIC_OBSERVED"
    assert observed["formation"] == "3-4-2-1"
    assert observed["coach_fit_score"] is None
    assert observed["formation_fit_score"] is None
    assert observed["cross_match_generalization_allowed"] is False
    assert ctx["coach_fit_requires_multiple_observed_role_and_manager_matches"] is True
    assert all(row["coach_fit"]["status"] == "UNAVAILABLE" for row in ctx["focus_players"])


def test_transferred_player_is_never_assumed_to_have_one_club_season_stats():
    mixed = deepcopy(UNDERSTAT)
    mixed["record_groups"]["players"][0]["team_title"] = "Chelsea,Manchester City"
    ctx = build(understat=mixed)
    palmer = next(row for row in ctx["players"] if row["official_element_id"] == 154)
    source = palmer["provider_skill_observation"]
    assert source["mixed_team_season"] is True
    assert source["club_specific_team_fit"] == "UNAVAILABLE_MIXED_TEAM_SEASON"
    assert source["season_aggregate_only"] is True


def test_source_consumption_ledger_distinguishes_verified_eligible_and_consumed():
    ctx = build()
    understat = ctx["source_health"]["understat"]
    assert understat["source_records"] == 2
    assert understat["verified_source_identity_rows"] == 1
    assert understat["eligible_verified_rows"] == 1
    assert understat["consumed_rows"] == understat["verified_join_count"] == 1
    assert understat["source_gate"] == "PASS"
    assert understat["rejected_reasons"] == {"SOURCE_IDENTITY_UNVERIFIED": 1}
    fotmob = ctx["source_health"]["fotmob"]
    assert fotmob["source_records"] == 1
    assert fotmob["verified_source_identity_rows"] == 1
    assert fotmob["eligible_verified_rows"] == 1
    assert fotmob["historical_scope_rows"] == 1
    assert fotmob["consumed_rows"] == fotmob["verified_match_count"] == 1
    assert fotmob["source_gate"] == "PASS"


def test_temporal_gate_preserves_verified_counts_without_fake_deep_consumption():
    ctx = build(report_slot="2026-10-13T09:00:00+07:00")
    understat = ctx["source_health"]["understat"]
    assert understat["verified_source_identity_rows"] == 1
    assert understat["eligible_verified_rows"] == understat["consumed_rows"] == 0
    assert understat["source_gate"] == "SOURCE_AFTER_REPORT_CUTOFF"
    assert understat["rejected_reasons"]["SOURCE_AFTER_REPORT_CUTOFF"] == 2
    fotmob = ctx["source_health"]["fotmob"]
    assert fotmob["verified_source_identity_rows"] == 1
    assert fotmob["eligible_verified_rows"] == fotmob["consumed_rows"] == 0
    assert fotmob["source_gate"] == "SOURCE_AFTER_REPORT_CUTOFF"
    assert fotmob["rejected_reasons"]["SOURCE_AFTER_REPORT_CUTOFF"] == 1


def test_verified_external_identity_outside_official_universe_is_not_consumed():
    source = deepcopy(UNDERSTAT)
    source["record_groups"]["players"].append({
        "source_native_id": 123456, "official_element_id": 999888,
        "identity_status": "VERIFIED", "games": 6, "time": 450, "xg": 2.3,
    })
    ctx = build(understat=source)
    ledger = ctx["source_health"]["understat"]
    assert ledger["verified_source_identity_rows"] == 2
    assert ledger["eligible_verified_rows"] == 2
    assert ledger["consumed_rows"] == 1
    assert ledger["rejected_reasons"]["VERIFIED_BUT_NOT_CONSUMED"] == 1
    assert len(ctx["players"]) == len(BOOTSTRAP["elements"])


def test_fotmob_rejections_and_out_of_scope_never_become_consumed():
    source = deepcopy(FOTMOB)
    duplicate = deepcopy(source["record_groups"]["fixtures"][0])
    source["record_groups"]["fixtures"].append(duplicate)
    out_of_scope = deepcopy(duplicate)
    out_of_scope["round"] = "8"
    source["record_groups"]["fixtures"].append(out_of_scope)
    ctx = build(fotmob=source)
    ledger = ctx["source_health"]["fotmob"]
    assert ledger["source_records"] == 3
    assert ledger["verified_source_identity_rows"] == 3
    assert ledger["historical_scope_rows"] == 2
    assert ledger["out_of_historical_scope"] == 1
    assert ledger["consumed_rows"] == 1
    assert ledger["rejected_reasons"]["UNVERIFIED_OR_DUPLICATE_FIXTURE"] == 1


def test_active_materializer_binds_exact_occurrence_source_context(monkeypatch, tmp_path):
    import gzip
    import json
    from src.engines import report_materializer as materializer

    slot = "2026-10-14T21:30:00+07:00"
    generated = "2026-10-14T14:45:00+00:00"
    original = {
        "contract": "OFFICIAL_DETAIL_FULL_SEASON_HISTORY_V1",
        "generated_at": generated,
        "report_prefetch_run_id": "prefetch-431",
        "target_logical_report_slot": slot,
    }
    historical = {
        "contract": "OFFICIAL_FULL_SEASON_PLAYER_HISTORY_V1",
        "players": {
            "154": {"team": 6, "position": 3, "history": {
                "6": {"status": "FINAL", "fixture_count": 1, "aggregate": {"minutes": 90}}}},
            "40": {"team": 2, "position": 3, "history": {
                "6": {"status": "FINAL", "fixture_count": 1, "aggregate": {"minutes": 80}}}},
        },
        "coverage_gate": {"status": "PASS", "all_historical_gws_finalized": True},
    }

    def save(relative, payload, *, zipped=False):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload).encode("utf-8")
        path.write_bytes(gzip.compress(serialized) if zipped else serialized)

    save("v6/history/official_detail.json.gz",
         {**original, "full_season_history": historical}, zipped=True)
    save("v6/normalized/canonical_players.json", {
        "effective_at": "2026-10-14T14:35:00Z",
        "players": [
            {"official_fpl_element_id": 154, "web_name": "Palmer"},
            {"official_fpl_element_id": 40, "web_name": "Rogers"},
        ]})
    save("v6/normalized/canonical_fixtures.json", {
        "effective_at": "2026-10-14T14:35:00Z",
        "fixtures": [
            {"official_fpl_fixture_id": 53, "event": 6,
             "team_h": 6, "team_a": 2, "finished": True},
        ]})
    external = deepcopy(UNDERSTAT)
    external["effective_at"] = "2026-10-14T14:35:00Z"
    external["record_groups"]["players"][0]["team_title"] = "Chelsea"
    external["record_groups"]["players"].append({
        "source_native_id": 9001, "official_element_id": 40,
        "identity_status": "VERIFIED", "time": 400, "xg": 1.5,
        "team_title": "Aston Villa",
    })
    fotmob = deepcopy(FOTMOB)
    fotmob["effective_at"] = "2026-10-14T14:35:00Z"
    fotmob["record_groups"]["teams"][1]["official_team_id"] = 2
    fotmob["record_groups"]["fixtures"][0]["away"]["source_native_id"] = 8678
    save("v6/normalized/sources/understat.json", external)
    save("v6/normalized/sources/fotmob.json", fotmob)
    monkeypatch.setattr(materializer, "DATA", tmp_path)
    ctx = materializer._bound_retrospective_context(
        original_official=original, logical_slot=slot, report_kind="full_master",
    )
    assert ctx["binding"]["prefetch_run_id"] == "prefetch-431"
    assert ctx["source_cutoff_at"] == generated
    assert ctx["observation_cutoff_mode"] == "OCCURRENCE_BOUND_PREFETCH_GENERATED_AT"
    assert ctx["historical_predeadline_source_asof_admission"] == "NOT_ASSERTED"
    assert ctx["source_health"]["understat"]["consumed_rows"] == 2
    assert ctx["source_health"]["fotmob"]["consumed_rows"] == 1
    assert {r["team_id"] for r in ctx["focus_players"]} == {2, 6}
    assert "players" not in ctx
    assert ctx["effect_on_projection"] == "NONE_ADVISORY_ONLY"


def test_active_materializer_rejects_late_source_or_mismatched_original_archive(monkeypatch, tmp_path):
    import gzip
    import json
    from src.engines import report_materializer as materializer
    original = {
        "contract": "OFFICIAL_DETAIL_FULL_SEASON_HISTORY_V1",
        "generated_at": "2026-10-14T14:15:00Z",
        "target_logical_report_slot": "2026-10-14T21:30:00+07:00",
        "report_prefetch_run_id": "prefetch-431",
    }
    archive = {**original, "full_season_history": {
        "contract": "OFFICIAL_FULL_SEASON_PLAYER_HISTORY_V1",
        "players": {"154": {"team": 6, "position": 3, "history": {}}},
        "coverage_gate": {"status": "PASS"},
    }}
    path = tmp_path / "v6/history/official_detail.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(archive).encode("utf-8")))
    source = deepcopy(UNDERSTAT)
    source["effective_at"] = "2026-10-14T22:35:00+07:00"
    p = tmp_path / "v6/normalized/sources/understat.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr(materializer, "DATA", tmp_path)
    ctx = materializer._bound_retrospective_context(
        original_official=original,
        logical_slot="2026-10-14T21:30:00+07:00", report_kind="full_master",
    )
    assert ctx["source_health"]["understat"]["verified_source_identity_rows"] == 1
    assert ctx["source_health"]["understat"]["consumed_rows"] == 0
    assert ctx["source_health"]["understat"]["source_gate"] == "SOURCE_AFTER_REPORT_CUTOFF"
    assert materializer._bound_retrospective_context(
        original_official={**original, "report_prefetch_run_id": "different"},
        logical_slot="2026-10-14T21:30:00+07:00", report_kind="full_master",
    ) == {}


def test_advisory_source_after_logical_slot_before_bound_prefetch_is_joinable():
    ctx = build(report_slot="2026-10-13T19:00:00+07:00",
                observation_cutoff_at="2026-10-13T12:45:00+00:00")
    assert ctx["report_logical_slot"] == "2026-10-13T19:00:00+07:00"
    assert ctx["source_cutoff_at"] == "2026-10-13T12:45:00+00:00"
    assert ctx["observation_cutoff_mode"] == "OCCURRENCE_BOUND_PREFETCH_GENERATED_AT"
    assert ctx["historical_predeadline_source_asof_admission"] == "NOT_ASSERTED"
    assert ctx["source_health"]["understat"]["consumed_rows"] == 1
    assert ctx["source_health"]["fotmob"]["consumed_rows"] == 1


def test_actual_prefetch_cutoff_still_rejects_future_source_and_naive_timestamp():
    ctx = build(report_slot="2026-10-13T19:00:00+07:00",
                observation_cutoff_at="2026-10-13T12:30:00+00:00")
    assert ctx["source_health"]["understat"]["source_gate"] == "SOURCE_AFTER_REPORT_CUTOFF"
    assert ctx["source_health"]["understat"]["consumed_rows"] == 0
    assert ctx["source_health"]["fotmob"]["consumed_rows"] == 0
    import pytest
    with pytest.raises(ValueError, match="timezone-aware"):
        build(observation_cutoff_at="2026-10-13T12:45:00")


def test_fotmob_tactical_details_use_only_verified_native_id_crosswalk():
    from src.runtime_v6.domains.acquisition.fotmob_tactics import normalize_match_details

    fixture = {
        "source_native_id": 5795467, "official_fixture_id": 53,
        "round": "6", "identity_status": "VERIFIED_MANUAL",
        "home": {"source_native_id": 8455, "official_team_id": 6,
                 "identity_status": "VERIFIED_MANUAL"},
        "away": {"source_native_id": 8678, "official_team_id": 3,
                 "identity_status": "VERIFIED_MANUAL"},
    }
    detail = {
        "general": {"matchId": "5795467", "leagueId": 47,
                    "homeTeam": {"id": 8455}, "awayTeam": {"id": 8678}},
        "content": {"lineup": {
            "homeTeam": {"id": 8455, "formation": "3-4-2-1",
                         "coach": {"id": 101, "name": "Xabi Alonso"},
                         "starters": [{"id": 1001, "positionId": 10,
                                       "horizontalLayout": {"x": 0.86, "y": 0.42}},
                                      {"id": 9999, "positionId": 9}],
                         "subs": [{"id": 1002}, {"id": 1001}],
                         "unavailable": [{"id": 1003, "unavailability": {
                             "type": "suspension", "expectedReturnDate": "2026-10-20T00:00:00Z"}},
                             {"id": 1002, "unavailability": {"type": "injury"}}]},
            "awayTeam": {"id": 8678, "formation": "4-2-3-1",
                         "coach": {"name": "Coach B"}, "starters": []},
        }},
    }
    records = normalize_match_details(
        detail, fixture, {"1001": (154, "VERIFIED_MANUAL"),
                          "1002": (40, "VERIFIED_MANUAL"),
                          "1003": (165, "VERIFIED_MANUAL"),
                          "9999": (165, "UNMAPPED")},
    )
    assert records is not None
    assert records["pstart_probability_applied"] is False
    home = records["sides"][0]
    assert home["formation"] == "3-4-2-1"
    assert home["coach"]["name"] == "Xabi Alonso"
    assert home["verified_starter_count"] == 1
    assert home["unverified_provider_starter_ids"] == [9999]
    assert home["unverified_starter_identity_semantics"] == "NATIVE_ID_REVIEW_ONLY_NO_CANONICAL_ATTRIBUTION"
    assert home["verified_official_starters"][0]["official_element_id"] == 154
    assert home["verified_official_starters"][0]["tactical_role"] is None
    assert home["verified_official_starters"][0]["observed_pitch_layout"]["x"] == 0.86
    assert home["verified_official_starters"][0]["observed_pitch_layout"]["semantic_role"] is None
    assert home["verified_official_bench"][0]["official_element_id"] == 40
    assert len(home["verified_official_bench"]) == 1  # a starter cannot also be bench
    assert home["verified_official_unavailable"][0]["official_element_id"] == 165
    assert home["verified_official_unavailable"][0]["reported_unavailability_type"] == "suspension"
    assert home["verified_official_unavailable"][0]["forecast_availability_eligible"] is False
    assert home["auxiliary_selection_conflict_count"] == 2
    wrong = deepcopy(detail)
    wrong["general"]["awayTeam"]["id"] = 100
    assert normalize_match_details(wrong, fixture, {}) is None
    unknown = dict(fixture, identity_status="UNMAPPED")
    assert normalize_match_details(detail, unknown, {}) is None


def test_occurrence_bound_tactical_history_is_descriptive_not_numeric():
    _check_espn_native_lineup_coverage_regression()
    _check_t1_fotmob_public_ssr_under_original_budget()
    _check_espn_dual_source_fixture_join_fail_closed()
    _check_manager_role_longitudinal_regression()
    _check_independent_espn_historical_acquisition_does_not_promote_fotmob()

    source = deepcopy(FOTMOB)
    digest = "a" * 64
    source["source_snapshot_ids"] = [digest]
    source["record_groups"]["match_tactics"] = [{
        "contract": "V6_FOTMOB_MATCH_TACTICS_V1",
        "source_snapshot_sha256": digest,
        "official_fixture_id": 53, "source_native_fixture_id": 5795467,
        "fixture_join": "VERIFIED_NATIVE_TO_OFFICIAL", "gw": "6",
        "sides": [
            {"side": "home", "official_team_id": 6,
             "coach": {"name": "Xabi Alonso"}, "formation": "3-4-2-1",
             "unverified_provider_starter_ids": [9999],
             "verified_official_starters": [
                {"official_element_id": 154, "identity_status": "VERIFIED_MANUAL",
                 "provider_position_id": 10,
                 "observed_pitch_layout": {"x": 0.86, "y": 0.42,
                     "coordinate_system": "FOTMOB_HORIZONTAL_LAYOUT"}},
             ],
             "verified_official_bench": [{"official_element_id": 165,
                  "identity_status": "VERIFIED_MANUAL",
                  "selection_class": "PROVIDER_REPORTED_MATCHDAY_BENCH"}],
             "verified_official_unavailable": [{"official_element_id": 40,
                  "identity_status": "VERIFIED_MANUAL",
                  "selection_class": "PROVIDER_REPORTED_UNAVAILABLE",
                  "reported_unavailability_type": "suspension"}]},
        ],
    }]
    _check_t1_official_independent_starter_coverage_does_not_depend_on_fotmob()
    ctx = build(fotmob=source, tactical_observation={})
    observed = ctx["focus_team"]["tactical_observation"]
    assert observed["status"] == "MATCH_SPECIFIC_OBSERVED"
    assert observed["manager"] == "Xabi Alonso"
    assert observed["formation"] == "3-4-2-1"
    assert ctx["match_tactics_verified_team_observations"] == 1
    assert observed["coach_fit_score"] is None
    assert observed["formation_fit_score"] is None
    assert ctx["effect_on_projection"] == "NONE_ADVISORY_ONLY"
    assert ctx["focus_team"]["verified_tactical_match_history"][0]["verified_player_roles"]["154"]["role"] is None
    assert ctx["focus_team"]["verified_tactical_match_history"][0]["unverified_native_starter_ids"] == [9999]
    shadow = ctx["focus_team"]["verified_selection_and_rotation_shadow"]
    assert shadow["observed_team_match_count"] == 1
    assert shadow["verified_starter_observation_count"] == 1
    assert shadow["verified_provider_bench_observation_count"] == 1
    assert shadow["verified_provider_unavailable_observation_count"] == 1
    assert shadow["reported_unavailability"][0]["element_id"] == 40
    assert shadow["reported_unavailability"][0]["historical_predeadline_asof_proven"] is False
    palmer_shadow = next(p for p in shadow["per_player"] if p["element_id"] == 154)
    assert palmer_shadow["observed_provider_slot_ids"] == [10]
    assert palmer_shadow["observed_pitch_layouts"][0]["x"] == 0.86
    assert shadow["semantic_tactical_roles_verified"] is False
    assert shadow["pregame_availability_asof_verified"] is False
    assert shadow["numeric_pstart_effect"] == "NONE"
    # A Chelsea focus view MUST NOT hide the rest of the 20-club universe.
    all_clubs = ctx["all_clubs_tactical_coverage"]
    assert all_clubs["contract"] == "V12_ALL_CLUBS_TACTICAL_COVERAGE_V1"
    assert {club["team_id"] for club in all_clubs["clubs"]} == {3, 6, 15}
    assert all_clubs["verified_team_fixture_observations"] == 0  # Official fixture still provisional.
    assert all_clubs["predeadline_asof_proven"] is False
    assert all_clubs["numeric_pstart_effect"] == "NONE"

    from src.engines.v12_gw1_gw6_history_context import _all_clubs_tactical_coverage
    full_league = {
        "teams": [{"id": team, "name": f"Club {team}"} for team in range(1, 21)],
        "elements": [{"id": team, "team": team} for team in range(1, 21)],
    }
    sixty = [
        {"id": gw * 10 + i, "event": gw, "team_h": 2 * i + 1,
         "team_a": 2 * i + 2, "finished": True}
        for gw in range(1, 7) for i in range(10)
    ]
    single_team = [{
        "team_id": 1, "fixture_id": 10, "gw": 1, "manager": "Recorded Coach",
        "formation": "4-3-3", "source_snapshot_sha256": "a" * 64,
        "verified_player_roles": {"101": {"provider_position_id": 7}},
        "unverified_native_starter_ids": [7777, 8888],
        "verified_bench_players": {}, "verified_unavailable_players": {},
    }]
    league = _all_clubs_tactical_coverage(full_league, sixty, single_team, list(range(1, 7)))
    assert league["scoped_club_count"] == 20
    assert league["expected_finalized_team_fixture_observations"] == 120
    assert league["verified_team_fixture_observations"] == 1
    assert league["complete_coach_formation_club_count"] == 0
    assert len(league["clubs"]) == 20
    assert league["clubs"][0]["unmapped_expected_starter_slots"] == 10
    assert league["clubs"][0]["unverified_native_starter_ids"] == [7777, 8888]
    assert league["clubs"][0]["unverified_native_starter_observation_count"] == 2
    assert league["clubs"][0]["coach_formation_coverage"] == "RETROSPECTIVE_PARTIAL"
    assert league["clubs"][0]["missing_official_fixture_ids"] == [20, 30, 40, 50, 60]
    assert league["clubs"][-1]["verified_tactical_team_fixture_count"] == 0
    assert league["role_semantics"] == "UNVERIFIED_POSITION_PROXY_ONLY"
    assert league["availability_semantics"] == "POST_MATCH_PROVIDER_REPORT_NOT_PREDEADLINE"
    # A provider observation from a different immutable source object is not valid.
    source["source_snapshot_ids"] = ["b" * 64]
    rejected = build(fotmob=source, tactical_observation={})
    assert rejected["match_tactics_verified_team_observations"] == 0
    assert rejected["focus_team"]["tactical_observation"]["status"] == "UNAVAILABLE"
    _check_t1_ledger_uses_official_starts_and_retains_unverified_tactical_role()
    _check_t1_three_way_duplicate_tactical_records_never_re_admit_conflict()


def test_v6_fotmob_adapter_normalizes_declared_match_details_without_fuzzy_join():
    from src.runtime_v6.domains.acquisition.source_native import _fotmob

    def link(official_key, official, native):
        return {official_key: official, "links": {
            "fotmob": {"status": "VERIFIED_MANUAL", "source_native_id": native},
        }}

    identity = {
        "mappings": {"154": link("official_fpl_element_id", 154, 1001)},
        "entity_bridges": {
            "fixture": {"mappings": {"53": link("official_fpl_fixture_id", 53, 5795467)}},
            "team": {"mappings": {
                "6": link("official_fpl_team_id", 6, 8455),
                "3": link("official_fpl_team_id", 3, 8678),
            }},
        },
    }
    detail = {
        "general": {"matchId": "5795467", "leagueId": 47,
                    "homeTeam": {"id": 8455}, "awayTeam": {"id": 8678}},
        "content": {"lineup": {
            "homeTeam": {"id": 8455, "formation": "3-4-2-1",
                         "coach": {"name": "Xabi Alonso"},
                         "starters": [{"id": 1001, "positionId": 10}]},
            "awayTeam": {"id": 8678, "formation": "4-4-2",
                         "coach": {"name": "Coach B"}, "starters": []},
        }},
    }
    source = {
        "health": "GREEN", "checked_at": "2026-10-13T12:31:00+00:00",
        "data": {
            "league": {"json": {"details": {"id": 47, "selectedSeason": "2026/2027"},
                               "matches": [{
                                   "id": 5795467, "round": "6",
                                   "home": {"id": 8455, "name": "Chelsea"},
                                   "away": {"id": 8678, "name": "Bournemouth"},
                                   "status": {"finished": True, "scoreStr": "5 - 1"},
                               }]}},
            "match_details_5795467": {"json": detail, "sha256": "a" * 64},
        },
    }
    normalized = _fotmob(source, identity)
    assert normalized["normalization_status"] == "NORMALIZED"
    rows = normalized["record_groups"]["match_tactics"]
    assert len(rows) == 1
    assert rows[0]["source_snapshot_sha256"] == "a" * 64
    assert rows[0]["sides"][0]["verified_official_starters"][0]["official_element_id"] == 154
    assert rows[0]["pstart_probability_applied"] is False
    source["data"]["match_details_5795467"]["json"]["general"]["matchId"] = "1"
    assert _fotmob(source, identity)["record_groups"]["match_tactics"] == []
    # Same mandatory governed node: acquisition regression must actually run.
    _check_t1_fotmob_candidate_selection_requires_finality_and_prioritizes_chelsea()
    import pytest
    with pytest.MonkeyPatch.context() as patch:
        _check_t1_fotmob_backfill_uses_original_v6_poll_and_keeps_immutable_source_sha(patch)
        _check_t1_fotmob_budget_and_provider_failure_stay_partial(patch)




def _check_t1_ledger_uses_official_starts_and_retains_unverified_tactical_role():
    history = deepcopy(HISTORY)
    history["generated_at"] = "2026-10-13T12:32:00Z"
    history["coverage_gate"]["fixture_identity_status"] = "PASS"
    history["players"]["154"]["history"]["6"] = {
        "status": "FINAL", "fixture_count": 1,
        "fixtures": [{"fixture": 53, "round": 6, "starts": 1, "minutes": 82}],
        "aggregate": {"minutes": 82},
    }
    fixtures = deepcopy(FPL_FIXTURES)
    fixtures[0]["finished"] = True
    source = deepcopy(FOTMOB)
    digest = "c" * 64
    source["source_snapshot_ids"] = [digest]
    source["record_groups"]["match_tactics"] = [{
        "contract": "V6_FOTMOB_MATCH_TACTICS_V1",
        "source_snapshot_sha256": digest,
        "official_fixture_id": 53, "source_native_fixture_id": 5795467,
        "fixture_join": "VERIFIED_NATIVE_TO_OFFICIAL", "gw": 6,
        "sides": [{
            "side": "home", "official_team_id": 6,
            "coach": {"name": "Coach One", "source_native_id": 101},
            "formation": "4-2-3-1",
            "verified_official_starters": [{
                "official_element_id": 154, "identity_status": "VERIFIED_MANUAL",
                "provider_position_id": 10,
            }],
        }],
    }]
    ctx = build(full_history=history, official_fixtures=fixtures,
                fotmob=source, tactical_observation={})
    rows = ctx["verified_context_ledger"]["rows"]
    palmer = next(r for r in rows if r["element_id"] == 154 and r["gw"] == 6)
    assert palmer["admission_status"] == "OBSERVED_VERIFIED"
    assert palmer["fixture_id"] == 53
    assert palmer["started"] is True
    assert palmer["minutes"] == 82
    assert palmer["coach_id"] == 101
    assert palmer["formation"] == "4-2-3-1"
    assert palmer["observed_role"] is None
    assert palmer["provider_position_id"] == 10
    assert palmer["availability"] == "UNKNOWN"
    assert palmer["finalized_at"] is None
    assert palmer["numeric_context_eligible"] is False
    assert palmer["historical_predeadline_asof_proven"] is False
    assert ctx["verified_context_ledger"]["by_position"]["MID"]["OBSERVED_VERIFIED"] == 1
    assert ctx["effect_on_projection"] == "NONE_ADVISORY_ONLY"

    # Real Official fixture mismatch cannot be counted as a verified start.
    wrong = deepcopy(fixtures)
    wrong[0]["team_h"] = 99
    rejected = build(full_history=history, official_fixtures=wrong,
                     fotmob=source, tactical_observation={})
    invalid = next(r for r in rejected["verified_context_ledger"]["rows"]
                   if r["element_id"] == 154 and r["gw"] == 6)
    assert invalid["admission_status"] == "REJECTED"
    assert invalid["rejection_reason"] == "PLAYER_CLUB_FIXTURE_MISMATCH"
    assert invalid["started"] is None
    assert invalid["coach_id"] is None


def _check_t1_three_way_duplicate_tactical_records_never_re_admit_conflict():
    source = deepcopy(FOTMOB)
    digest = "e" * 64
    source["source_snapshot_ids"] = [digest]
    row = {
        "contract": "V6_FOTMOB_MATCH_TACTICS_V1",
        "source_snapshot_sha256": digest,
        "official_fixture_id": 53, "source_native_fixture_id": 5795467,
        "fixture_join": "VERIFIED_NATIVE_TO_OFFICIAL", "gw": "6",
        "sides": [{"side": "home", "official_team_id": 6,
                   "coach": {"name": "Coach One"}, "formation": "4-3-3",
                   "verified_official_starters": []}],
    }
    source["record_groups"]["match_tactics"] = [deepcopy(row) for _ in range(3)]
    ctx = build(fotmob=source, tactical_observation={})
    assert ctx["match_tactics_verified_team_observations"] == 0
    assert ctx["focus_team"]["verified_tactical_match_history"] == []
    assert ctx["focus_team"]["tactical_observation"]["status"] == "UNAVAILABLE"

from src.runtime_v6.domains.acquisition import adapters
from src.runtime_v6.domains.acquisition.fotmob_backfill import collect_fotmob, finalized_match_ids

def _match(native, gw=6, finished=True, home=8455):
    return {
        "id": native, "round": str(gw),
        "home": {"id": home}, "away": {"id": 8678},
        "status": {"finished": finished, "cancelled": False},
    }


def _source():
    return {
        "id": "fotmob", "adapter": "http", "critical": False,
        "match_details_history": {
            "enabled": True,
            "historical_gws": [1, 2, 3, 4, 5, 6],
            "priority_native_team_ids": [8455],
            "max_backfill_requests_per_cycle": 2,
            "daily_request_budget": 4,
            "max_body_bytes": 200000,
            "endpoint_template": "https://www.fotmob.com/api/data/matchDetails?matchId={match_id}",
        },
    }


def _base():
    return {
        "health": "GREEN", "checked_at": "2026-10-15T00:00:00Z",
        "data": {"league": {
            "status": "AVAILABLE", "sha256": "f" * 64,
            "json": {"details": {"id": 47, "selectedSeason": "2026/2027"},
                     "matches": [_match(102, 1, home=9825), _match(101),
                                 _match(103, 7), _match(104, 3, finished=False)]},
        }},
        "coverage": {}, "changed": False,
    }


class _Client:
    retry_attempts = 2

    def __init__(self):
        self.requests = []

    def fetch(self, source, request, previous=None):
        self.requests.append(request["id"])
        native = int(request["id"].removeprefix("match_details_"))
        return {
            "request_id": request["id"], "status": "AVAILABLE",
            "json": {"general": {"matchId": native},
                     "content": {"lineup": {"homeTeam": {}, "awayTeam": {}}}},
            "sha256": f"{native:064x}",
            "checked_at": "2026-10-15T00:20:00Z",
        }


def _check_t1_fotmob_candidate_selection_requires_finality_and_prioritizes_chelsea():
    league = _base()["data"]["league"]["json"]
    cfg = _source()["match_details_history"]
    assert finalized_match_ids(league, cfg) == [101, 102]
    # Three repeated provider fixture IDs must never be re-admitted.
    league["matches"].extend([_match(101), _match(101)])
    assert finalized_match_ids(league, cfg) == [102]


def _check_t1_fotmob_backfill_uses_original_v6_poll_and_keeps_immutable_source_sha(monkeypatch):
    client = _Client()
    source = _source()
    monkeypatch.setattr(adapters, "collect_http", lambda *args: deepcopy(_base()))
    first = adapters.collect_source(source, client)
    assert client.requests == ["match_details_101", "match_details_102"] or sorted(client.requests) == [
        "match_details_101", "match_details_102",
    ]
    assert first["match_details_history"]["status"] == "RETRIEVAL_COMPLETE"
    assert first["match_details_history"]["historical_predeadline_asof_proven"] is False
    assert first["match_details_history"]["identity_and_tactical_admission"] == "NOT_ASSERTED"
    assert first["data"]["match_details_101"]["sha256"] == f"{101:064x}"
    assert first["data"]["match_details_102"]["sha256"] == f"{102:064x}"
    next_run = collect_fotmob(source, client, first)
    assert len(client.requests) == 2
    assert next_run["match_details_history"]["cached_finalized_match_details"] == 2
    assert next_run["data"]["match_details_101"]["data_origin"] == "FINALIZED_MATCH_DETAILS_CACHE"
    assert next_run["data"]["match_details_101"]["checked_at"] == "2026-10-15T00:20:00Z"
    assert next_run["match_details_history"]["new_scheduler_created"] is False


def _check_t1_fotmob_budget_and_provider_failure_stay_partial(monkeypatch):
    source = _source()
    monkeypatch.setattr(adapters, "collect_http", lambda *args: deepcopy(_base()))
    class Unavailable(_Client):
        def fetch(self, source, request, previous=None):
            self.requests.append(request["id"])
            return {"request_id": request["id"], "status": "UNAVAILABLE", "http_status": 403}
    client = Unavailable()
    first = collect_fotmob(source, client)
    assert first["health"] == "GREEN"  # League still works, noncritical enrichment is isolated.
    assert first["match_details_history"]["status"] == "PARTIAL"
    assert first["match_details_history"]["remaining_without_usable_details"] == 2
    assert first["match_details_history"]["reserved_attempts_today"] == 4
    assert first["match_details_history"]["attempt_failures"]
    second = collect_fotmob(source, client, first)
    assert second["match_details_history"]["attempted_this_cycle"] == 0
    assert len(client.requests) == 2


def _check_t1_official_independent_starter_coverage_does_not_depend_on_fotmob():
    from src.engines.v12_gw1_gw6_history_context import _official_fixture_starter_coverage
    fixtures = [
        {"id": 1234, "event": 1, "team_h": 6, "team_a": 3, "finished": True},
        {"id": 1235, "event": 1, "team_h": 15, "team_a": 1, "finished": False},
    ]
    rows = [
        {"fixture_id": 1234, "team_id": team, "element_id": team * 100 + player,
         "admission_status": "OBSERVED_VERIFIED", "started": True, "minutes": 90}
        for team in (6, 3) for player in range(1, 12)
    ]
    observed = _official_fixture_starter_coverage(fixtures, {"rows": rows}, [1, 2, 3, 4, 5, 6])
    assert observed["finalized_official_fixture_count"] == 1
    assert observed["expected_finalized_team_fixture_sides"] == 2
    assert observed["complete_verified_starting_xis"] == 2
    assert observed["coverage_status"] == "COMPLETE"
    assert observed["coach_formation_status"] == "NOT_ESTABLISHED_BY_OFFICIAL_SELECTION"
    assert observed["fotmob_match_details_count_not_affected"] is True
    assert observed["numeric_pstart_effect"] == "NONE"

    # One missing Official starter cannot be patched using the provider lineup.
    missing = _official_fixture_starter_coverage(fixtures, {"rows": rows[:-1]}, [1])
    assert missing["coverage_status"] == "PARTIAL"
    assert missing["complete_verified_starting_xis"] == 1
    assert missing["incomplete_or_unverified_team_fixture_sides"] == 1
    # Duplicate and conflicting original fixture IDs fail closed.
    duplicate = _official_fixture_starter_coverage(fixtures + [fixtures[0]], {"rows": rows}, [1])
    assert duplicate["complete_verified_starting_xis"] == 0
    # Repeated Official player start is not counted twice as independent evidence.
    duplicate_starter = _official_fixture_starter_coverage(
        fixtures, {"rows": rows + [rows[0]]}, [1]
    )
    assert duplicate_starter["complete_verified_starting_xis"] == 1


def _check_independent_espn_historical_acquisition_does_not_promote_fotmob():
    import pytest
    from src.runtime_v6.domains.acquisition import adapters
    from src.runtime_v6.domains.acquisition.espn_historical import (
        verified_espn_events, collect_espn_history,
    )
    event = {
        "id": "401879285", "date": "2026-09-12T14:00:00Z",
        "competitions": [{
            "id": "401879285",
            "status": {"type": {"completed": True, "state": "post"}},
            "competitors": [
                {"homeAway": "home", "team": {"id": "349"}},
                {"homeAway": "away", "team": {"id": "337"}},
            ],
        }],
    }
    data = {"history_scoreboard_20260912": {
        "status": "AVAILABLE", "json": {"events": [event]},
    }}
    assert verified_espn_events(data, ["20260912"]) == [401879285]
    duplicated = {"history_scoreboard_20260912": {
        "status": "AVAILABLE", "json": {"events": [event, event]},
    }}
    assert verified_espn_events(duplicated, ["20260912"]) == []
    future = {"history_scoreboard_20260912": {
        "status": "AVAILABLE",
        "json": {"events": [{**event, "competitions": [{
            **event["competitions"][0],
            "status": {"type": {"completed": False, "state": "pre"}},
        }]}]},
    }}
    assert verified_espn_events(future, ["20260912"]) == []

    source = {"id": "espn", "adapter": "http", "critical": False,
              "historical_tactics": {
                  "enabled": True, "dates_yyyymmdd": ["20260912"],
                  "daily_request_budget": 6, "max_requests_per_cycle": 2,
                  "scoreboard_url_template": "https://site.api.espn.com/scoreboard?dates={date}",
                  "summary_url_template": "https://site.api.espn.com/summary?event={event_id}",
              }}
    class Client:
        retry_attempts = 2
        calls = []
        def fetch(self, src, request, previous=None):
            self.calls.append(request["id"])
            return {
                "request_id": request["id"], "status": "AVAILABLE",
                "sha256": "a" * 64,
                "json": (
                    {"leagues": [], "events": [event]}
                    if request["id"].startswith("history_scoreboard")
                    else {"header": {"id": 401879285}, "boxscore": {}}
                ),
            }
    client = Client()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(adapters, "collect_http", lambda *a: {
            "source_id": "espn", "health": "GREEN",
            "data": {}, "coverage": {}, "changed": False,
        })
        first = collect_espn_history(source, client)
        assert first["historical_tactics_coverage"]["history_dates_cached"] == 1
        assert first["historical_tactics_coverage"]["event_summaries_cached"] == 0
        second = collect_espn_history(source, client, first)
        assert second["historical_tactics_coverage"]["event_summaries_cached"] == 1
        assert second["historical_tactics_coverage"]["status"] == "RETRIEVAL_COMPLETE"
        assert second["historical_tactics_coverage"]["fotmob_matchdetails_coverage_not_modified"] is True
        assert second["historical_tactics_coverage"]["numeric_pstart_effect"] == "NONE"
        assert second["historical_tactics_coverage"]["new_scheduler_created"] is False
        assert client.calls == [
            "history_scoreboard_20260912", "history_summary_401879285"
        ]
        third = collect_espn_history(source, client, second)
        assert third["historical_tactics_coverage"]["requests_this_cycle"] == 0
        assert client.calls == [
            "history_scoreboard_20260912", "history_summary_401879285"
        ]

def _check_manager_role_longitudinal_regression():
    from src.engines.v12_gw1_gw6_history_context import _manager_role_longitudinal
    digest = "a" * 64
    b = {"teams": [{"id": 1, "name": "Club"}],
         "elements": [{"id": 10, "team": 1}, {"id": 11, "team": 1}]}
    one = {"fixture_id": 100, "gw": 1, "team_id": 1, "manager": "A",
           "manager_native_id": 7, "formation": "4-3-3",
           "source_snapshot_sha256": digest,
           "verified_player_roles": {"10": {"provider_position_id": 9}}}
    two = {"fixture_id": 110, "gw": 2, "team_id": 1, "manager": "B",
           "manager_native_id": 8, "formation": "3-4-3",
           "source_snapshot_sha256": digest,
           "verified_player_roles": {"10": {"provider_position_id": 11}}}
    out = _manager_role_longitudinal(b, [one, two])
    assert out["observed_manager_transitions"] == 1
    assert out["observed_formation_transitions"] == 1
    assert out["verified_starter_slot_observations"] == 2
    assert out["numeric_pstart_effect"] == "NONE"
    p = next(x for x in out["players"] if x["element_id"] == 10)
    assert p["provider_slot_counts"] == {"9": 1, "11": 1}
    assert p["semantic_role"] is None
    assert p["target_gw_role_start_probability"] is None
    assert p["historical_predeadline_asof_proven"] is False
    assert _manager_role_longitudinal(b, [one, one, two])["observed_manager_transitions"] == 0
    assert _manager_role_longitudinal(
        b, [dict(one, source_snapshot_sha256="bad")]
    )["verified_starter_slot_observations"] == 0


def _check_espn_dual_source_fixture_join_fail_closed():
    from src.engines.v12_espn_fixture_crosscheck import crosscheck_espn_historical_fixtures
    from copy import deepcopy
    sha = "a" * 64
    fm = {
        "source_id": "fotmob", "effective_at": "2026-10-15T09:50:00Z",
        "record_groups": {
            "teams": [
                {"source_native_id": 8472, "official_team_id": 20,
                 "name": "Sunderland", "identity_status": "VERIFIED_MANUAL"},
                {"source_native_id": 9825, "official_team_id": 1,
                 "name": "Arsenal", "identity_status": "VERIFIED_MANUAL"},
            ],
            "fixtures": [{
                "source_native_id": 5795453, "official_fixture_id": 36,
                "identity_status": "VERIFIED_MANUAL", "round": 4,
                "home": {"source_native_id": 8472},
                "away": {"source_native_id": 9825},
                "status": {"finished": True, "utcTime": "2026-09-12T19:00:00Z",
                           "scoreStr": "2 - 1"},
            }],
            "match_tactics": [],
        },
    }
    event = {
        "id": "401878779", "date": "2026-09-12T19:00Z",
        "competitions": [{
            "id": "401878779",
            "status": {"type": {"completed": True, "state": "post"}},
            "competitors": [
                {"homeAway": "home", "team": {"displayName": "Sunderland"}, "score": "2"},
                {"homeAway": "away", "team": {"displayName": "Arsenal"}, "score": "1"},
            ],
        }],
    }
    espn = {
        "source_id": "espn", "checked_at": "2026-10-15T09:55:00Z",
        "data": {"history_scoreboard_20260912": {
            "status": "AVAILABLE", "sha256": sha,
            "json": {"events": [event]},
        }},
    }
    result = crosscheck_espn_historical_fixtures(
        espn, fm, source_cutoff="2026-10-15T10:00:00Z"
    )
    assert result["status"] == "VERIFIED_FIXTURE_ONLY"
    assert result["verified_fixture_count"] == 1
    assert result["matched_missing_fotmob_detail_fixtures"] == 1
    assert result["missing_fotmob_detail_fixture_ids"] == [36]
    assert result["matches"][0]["official_fixture_id"] == 36
    assert result["lineup_or_tactical_role_admitted"] is False
    assert result["numeric_pstart_effect"] == "NONE"
    conflict = deepcopy(espn)
    conflict["data"]["history_scoreboard_20260912"]["json"]["events"].append(event)
    assert crosscheck_espn_historical_fixtures(
        conflict, fm, source_cutoff="2026-10-15T10:00:00Z"
    )["verified_fixture_count"] == 0
    failed_score = deepcopy(espn)
    failed_score["data"]["history_scoreboard_20260912"]["json"]["events"][0]["competitions"][0]["competitors"][0]["score"] = "3"
    assert crosscheck_espn_historical_fixtures(
        failed_score, fm, source_cutoff="2026-10-15T10:00:00Z"
    )["verified_fixture_count"] == 0
    assert crosscheck_espn_historical_fixtures(
        espn, fm, source_cutoff="2026-10-15T09:53:00Z"
    )["status"] == "SOURCE_UNAVAILABLE"


def _check_t1_fotmob_public_ssr_under_original_budget():
    import json
    import pytest
    from src.runtime_v6.domains.acquisition.fotmob_public_page import extract_verified_page_matchdetails
    from src.runtime_v6.domains.acquisition import adapters
    from src.runtime_v6.domains.acquisition.fotmob_backfill import collect_fotmob

    def html(native, starters=11):
        sides = {
            "homeTeam": {"id": 8455, "formation": "4-3-3",
                         "coach": {"id": 22, "name": "Verified Coach"},
                         "starters": [{"id": i + 1} for i in range(starters)]},
            "awayTeam": {"id": 8678, "formation": "4-2-3-1",
                         "coach": {"id": 44, "name": "Other Coach"},
                         "starters": [{"id": i + 22} for i in range(starters)]},
        }
        raw = {"props": {"pageProps": {
            "general": {"matchId": str(native), "leagueId": 47, "finished": True,
                        "homeTeam": {"id": 8455}, "awayTeam": {"id": 8678}},
            "content": {"lineup": sides},
        }}}
        return '<html><script type="application/json" id="__NEXT_DATA__">' + json.dumps(raw) + '</script></html>'

    assert extract_verified_page_matchdetails(html(101), 101)["general"]["matchId"] == "101"
    assert extract_verified_page_matchdetails(html(101), 102) is None
    assert extract_verified_page_matchdetails(html(101, starters=10), 101) is None
    assert extract_verified_page_matchdetails(html(101) + html(101), 101) is None
    assert extract_verified_page_matchdetails(html(101).replace('"id": 8455, "formation"', '"id": 9999, "formation"'), 101) is None

    source = _source()
    cfg = source["match_details_history"]
    cfg["public_page_fallback_enabled"] = True
    cfg["public_page_url_template"] = "https://www.fotmob.com/match/{match_id}"
    cfg["public_page_max_body_bytes"] = 1500000

    class PublicClient(_Client):
        def fetch(self, source, request, previous=None):
            self.requests.append(request["url"])
            assert "/match/" in request["url"]
            assert request["expect"] == "text"
            native = int(request["id"].removeprefix("match_details_"))
            return {"request_id": request["id"], "status": "AVAILABLE",
                    "sha256": "b" * 64, "body": html(native), "json": None}
    client = PublicClient()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(adapters, "collect_http", lambda *a: deepcopy(_base()))
        one = collect_fotmob(source, client)
        assert one["match_details_history"]["status"] == "RETRIEVAL_COMPLETE"
        assert one["match_details_history"]["fetched_public_page_ssr_this_cycle"] == 2
        assert one["match_details_history"]["cached_public_page_ssr_details"] == 2
        assert one["match_details_history"]["reserved_attempts_today"] == 4
        assert one["match_details_history"]["same_daily_fotmob_budget_for_api_and_page"] is True
        for n in (101, 102):
            result = one["data"]["match_details_" + str(n)]
            assert result["retrieval_method"] == "FOTMOB_PUBLIC_PAGE_SSR"
            assert result["source_original_html_retained"] is True
            assert result["not_original_api_matchdetails_response"] is True
            assert result["json"]["content"]["lineup"]["homeTeam"]["coach"]["name"] == "Verified Coach"
        two = collect_fotmob(source, client, one)
        assert two["match_details_history"]["attempted_this_cycle"] == 0
        assert len(client.requests) == 2


def _check_espn_native_lineup_coverage_regression():
    """ESPN source-native completed XI/formation is not Official player identity."""
    from copy import deepcopy
    from src.engines.v12_espn_native_tactics import verify_espn_native_lineup_coverage

    digest = "a" * 64
    fm = {
        "source_id": "fotmob", "effective_at": "2026-10-15T09:50:00Z",
        "record_groups": {
            "teams": [
                {"source_native_id": 8472, "official_team_id": 20,
                 "name": "Sunderland", "identity_status": "VERIFIED_MANUAL"},
                {"source_native_id": 9825, "official_team_id": 1,
                 "name": "Arsenal", "identity_status": "VERIFIED_MANUAL"},
            ],
            "fixtures": [{
                "source_native_id": 5795453, "official_fixture_id": 36,
                "identity_status": "VERIFIED_MANUAL", "round": "4",
                "home": {"source_native_id": 8472},
                "away": {"source_native_id": 9825},
                "status": {"finished": True, "utcTime": "2026-09-12T19:00:00Z",
                           "scoreStr": "2 - 1"},
            }],
            "match_tactics": [],
        },
    }
    sides = [
        {"homeAway": "home", "team": {"id": "366", "displayName": "Sunderland"}, "score": "2"},
        {"homeAway": "away", "team": {"id": "359", "displayName": "Arsenal"}, "score": "1"},
    ]
    event = {
        "id": "401878779", "date": "2026-09-12T19:00Z",
        "competitions": [{
            "id": "401878779",
            "status": {"type": {"completed": True, "state": "post"}},
            "competitors": sides,
        }],
    }
    summary = {
        "header": {"id": "401878779", "competitions": [{
            "id": "401878779", "date": "2026-09-12T19:00Z",
            "status": {"type": {"completed": True, "state": "post"}},
            "competitors": deepcopy(sides),
        }]},
        "rosters": [
            {"homeAway": side, "team": dict(sides[idx]["team"]),
             "formation": "4-2-3-1", "roster": [
                 {"athlete": {"id": str(idx * 20 + k + 1)}, "starter": True,
                  "position": {"displayName": "Forward"}} for k in range(11)
             ]}
            for idx, side in enumerate(("home", "away"))
        ],
    }
    espn = {
        "source_id": "espn", "checked_at": "2026-10-15T09:55:00Z",
        "data": {
            "history_scoreboard_20260912": {
                "status": "AVAILABLE", "sha256": digest, "json": {"events": [event]}},
            "history_summary_401878779": {
                "status": "AVAILABLE", "sha256": digest, "sha256_scope": "full_body",
                "checked_at": "2026-10-15T09:54:00Z", "json": summary},
        },
    }
    def check(source, cutoff="2026-10-15T10:00:00Z"):
        return verify_espn_native_lineup_coverage(
            source, fm, source_cutoff=cutoff
        )
    ok = check(espn)
    assert ok["status"] == "VERIFIED_ESPN_NATIVE_XI_ONLY"
    assert ok["native_espn_starting_xi_matches"] == 1
    assert ok["native_espn_starter_observations"] == 22
    assert ok["missing_fotmob_with_espn_native_xi"] == 1
    assert ok["combined_distinct_tactical_fixtures"] == 1
    assert ok["historical_fixture_denominator"] == 1
    assert ok["still_without_tactical_source_fixture_ids"] == []
    assert ok["source_native_observations"][0]["teams"][0]["official_fpl_starter_ids"] == []
    assert ok["espn_athlete_official_fpl_crosswalk"] == "NOT_ESTABLISHED"
    assert ok["numeric_pstart_effect"] == "NONE"
    for mut in ("duplicate", "formation", "score", "late", "sha"):
        bad = deepcopy(espn)
        item = bad["data"]["history_summary_401878779"]
        if mut == "duplicate":
            item["json"]["rosters"][0]["roster"][1]["athlete"]["id"] = "1"
        if mut == "formation":
            item["json"]["rosters"][0]["formation"] = "4-4-4"
        if mut == "score":
            item["json"]["header"]["competitions"][0]["competitors"][0]["score"] = "9"
        if mut == "late":
            item["checked_at"] = "2026-10-15T10:02:00Z"
        if mut == "sha":
            item["sha256"] = "invalid"
        assert check(bad)["native_espn_starting_xi_matches"] == 0, mut
    assert check(espn, cutoff="2026-10-15T09:53:00Z")["status"] == "SOURCE_UNAVAILABLE"
