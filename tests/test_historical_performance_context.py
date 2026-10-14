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
                         "starters": [{"id": 1001, "positionId": 10},
                                      {"id": 9999, "positionId": 9}]},
            "awayTeam": {"id": 8678, "formation": "4-2-3-1",
                         "coach": {"name": "Coach B"}, "starters": []},
        }},
    }
    records = normalize_match_details(
        detail, fixture, {"1001": (154, "VERIFIED_MANUAL"),
                          "9999": (165, "UNMAPPED")},
    )
    assert records is not None
    assert records["pstart_probability_applied"] is False
    home = records["sides"][0]
    assert home["formation"] == "3-4-2-1"
    assert home["coach"]["name"] == "Xabi Alonso"
    assert home["verified_starter_count"] == 1
    assert home["verified_official_starters"][0]["official_element_id"] == 154
    assert home["verified_official_starters"][0]["tactical_role"] is None
    wrong = deepcopy(detail)
    wrong["general"]["awayTeam"]["id"] = 100
    assert normalize_match_details(wrong, fixture, {}) is None
    unknown = dict(fixture, identity_status="UNMAPPED")
    assert normalize_match_details(detail, unknown, {}) is None


def test_occurrence_bound_tactical_history_is_descriptive_not_numeric():
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
             "verified_official_starters": [
                {"official_element_id": 154, "identity_status": "VERIFIED_MANUAL",
                 "provider_position_id": 10},
             ]},
        ],
    }]
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
    # A provider observation from a different immutable source object is not valid.
    source["source_snapshot_ids"] = ["b" * 64]
    rejected = build(fotmob=source, tactical_observation={})
    assert rejected["match_tactics_verified_team_observations"] == 0
    assert rejected["focus_team"]["tactical_observation"]["status"] == "UNAVAILABLE"
