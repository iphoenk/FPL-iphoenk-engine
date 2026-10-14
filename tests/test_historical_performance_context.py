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


def test_same_occurrence_prefetch_cutoff_admits_post_slot_advisory_source_without_backdating():
    # Logical slot 12:00Z, provider was checked at 12:31Z and the bound
    # prefetch did not finalize until 12:45Z. Both are pre-GW7, but neither
    # makes the source available at the historical 12:00Z logical timestamp.
    ctx = build(report_slot="2026-10-13T19:00:00+07:00",
                observation_cutoff_at="2026-10-13T12:45:00+00:00")
    assert ctx["report_logical_slot"] == "2026-10-13T19:00:00+07:00"
    assert ctx["source_cutoff_at"] == "2026-10-13T12:45:00+00:00"
    assert ctx["observation_cutoff_mode"] == "OCCURRENCE_BOUND_PREFETCH_GENERATED_AT"
    assert ctx["historical_predeadline_source_asof_admission"] == "NOT_ASSERTED"
    assert ctx["source_health"]["understat"]["consumed_rows"] == 1
    assert ctx["source_health"]["fotmob"]["consumed_rows"] == 1
    assert ctx["source_health"]["understat"]["report_cutoff_at"] == ctx["source_cutoff_at"]


def test_exact_prefetch_observation_cutoff_still_rejects_future_source_and_naive_time():
    ctx = build(report_slot="2026-10-13T19:00:00+07:00",
                observation_cutoff_at="2026-10-13T12:30:00+00:00")
    assert ctx["source_health"]["understat"]["source_gate"] == "SOURCE_AFTER_REPORT_CUTOFF"
    assert ctx["source_health"]["understat"]["consumed_rows"] == 0
    assert ctx["source_health"]["fotmob"]["consumed_rows"] == 0
    import pytest
    with pytest.raises(ValueError, match="timezone-aware"):
        build(observation_cutoff_at="2026-10-13T12:45:00")
