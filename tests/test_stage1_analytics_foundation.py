from __future__ import annotations

import json

from src.models.v12_analytics_foundation import (
    load_v6_analytics_foundation,
)
from src.models.v12_stage1_analytics import (
    build_canonical_universe,
    build_hierarchical_priors,
    distribution_selection_matrix,
    opponent_adjust_match_rows,
    regime_change_evidence,
    walk_forward_validate,
)


def _rows():
    rows = []
    for gw in range(1, 6):
        rows.extend(
            [
                {
                    "player_id": 1, "element": 1, "team_id": 1,
                    "position": "MID", "gw": gw, "match_id": 100 + gw,
                    "opponent_team_id": 2, "home": gw % 2 == 1,
                    "minutes": 90, "starter": True,
                    "xg": 0.15 * gw, "xa": 0.10,
                    "xgi": 0.15 * gw + 0.10,
                    "goals": int(gw == 5), "assists": 0,
                    "saves": 0, "bonus": 0, "defensive": 5,
                },
                {
                    "player_id": 2, "element": 2, "team_id": 2,
                    "position": "FWD", "gw": gw, "match_id": 200 + gw,
                    "opponent_team_id": 1, "home": gw % 2 == 0,
                    "minutes": 75 if gw < 4 else 90, "starter": True,
                    "xg": 0.25, "xa": 0.05 * gw,
                    "xgi": 0.25 + 0.05 * gw,
                    "goals": 0, "assists": int(gw == 4),
                    "saves": 0, "bonus": 0, "defensive": 3,
                },
            ]
        )
    return rows


def _strength():
    return {
        "teams": [
            {
                "team_id": 1, "attack_home_index": 1.2,
                "attack_away_index": 1.1, "defence_home_index": 1.15,
                "defence_away_index": 1.05,
            },
            {
                "team_id": 2, "attack_home_index": 0.9,
                "attack_away_index": 0.95, "defence_home_index": 0.8,
                "defence_away_index": 0.85,
            },
        ]
    }


def test_opponent_adjustment_and_hierarchy_are_deterministic():
    adjusted = opponent_adjust_match_rows(_rows(), _strength())
    assert all(row["opponent_strength_weight"] > 0 for row in adjusted)
    priors = build_hierarchical_priors(adjusted)
    assert priors["players"]["1"]["variables"]["xg90"]["prior_rate90"] >= 0
    assert priors["different_prior_strengths_by_variable"] is True
    assert priors["final_player_posterior_owner"] == "V12_PLAYER_EVENTS"


def test_distribution_selection_never_uses_erlang_generically():
    matrix = distribution_selection_matrix(_rows())["matrix"]
    assert matrix
    assert all(row.get("erlang_selected") is not True for row in matrix)
    assert any(row.get("target") == "goals" for row in matrix)


def test_walk_forward_is_expanding_window_without_future_leakage():
    result = walk_forward_validate(
        opponent_adjust_match_rows(_rows(), _strength())
    )
    assert result["future_leakage"] is False
    assert result["folds"] >= 1
    assert result["status"] == "PASS"
    assert result["starter_brier"]


def test_regime_change_publishes_role_stability_probability():
    result = regime_change_evidence(_rows()[:5])
    assert 0.0 <= result["p_role_stable"] <= 1.0
    assert result["history_hard_reset"] is False


def test_canonical_universe_uses_exact_macro_weights_and_owner_outputs_only():
    players = []
    for position in ("GK", "DEF", "MID", "FWD"):
        for index in range(6):
            element = len(players) + 1
            players.append(
                {
                    "element": element,
                    "name": f"P{element}",
                    "position": position,
                    "team_id": 1,
                    "now_cost": 50,
                    "status": "a",
                    "posterior_rates": {
                        "goal": {
                            "prior": 0.1 + index / 100,
                            "posterior_rate90": 0.12 + index / 100,
                        },
                        "assist": {
                            "prior": 0.08,
                            "posterior_rate90": 0.09,
                        },
                        "saves": {
                            "prior": 3.0,
                            "posterior_rate90": 3.1,
                        },
                        "defcon": {
                            "prior_expected_points90": 0.3,
                            "expected_points90": 0.4,
                        },
                    },
                    "xmins": {
                        "expected_minutes": 82.0,
                        "start_probability": 0.91,
                        "p_60_plus": 0.86,
                        "xmins_distribution": {
                            "distribution": "FINITE_STATE_MINUTES_MIXTURE"
                        },
                    },
                    "position_engine": {
                        "model": "POSITION_SPECIFIC_DISCRETE_POSTERIOR_PREDICTIVE_V1",
                        "matchup_vector": {
                            "model": "DYNAMIC_POSITION_ROLE_MATCHUP_VECTOR_V1",
                            "vector": {
                                key: {"multiplier": 1.0}
                                for key in (
                                    "goal", "creation", "attack",
                                    "clean_sheet", "defcon", "save",
                                    "set_piece", "aerial", "transition",
                                    "minutes", "bonus",
                                )
                            },
                        },
                    },
                    "tactical_role_component": {
                        "canonical_tactical_role_score": 50 + index
                    },
                    "horizons": {
                        "1": {
                            "mean": 4 + index / 10,
                            "point_distribution": {
                                "status": "READY_COMPLETE_CONDITIONAL_PMF",
                                "model": "EXACT_DISCRETE_CONVOLUTION_CONDITIONAL_ON_POSTERIOR",
                                "sum_probability": 1.0,
                            },
                        },
                        "3": {
                            "mean": 12 + index / 10,
                            "point_distribution": {
                                "status": "READY_COMPLETE_CONDITIONAL_PMF",
                                "model": "EXACT_DISCRETE_CONVOLUTION_CONDITIONAL_ON_POSTERIOR",
                                "sum_probability": 1.0,
                            },
                        },
                        "5": {
                            "mean": 20 + index / 10,
                            "point_distribution": {
                                "status": "READY_COMPLETE_CONDITIONAL_PMF",
                                "model": "EXACT_DISCRETE_CONVOLUTION_CONDITIONAL_ON_POSTERIOR",
                                "sum_probability": 1.0,
                            },
                        },
                    },
                }
            )
    out = build_canonical_universe({"players": players})
    assert out["status"] == "COMPLETE"
    assert out["weights"] == {
        "PROVEN_HISTORICAL": 0.20,
        "TACTICAL_ROLE": 0.25,
        "CURRENT_UNDERLYING": 0.30,
        "FIXTURE_SECURITY": 0.25,
    }
    assert all(
        row["canonical_evaluation_complete"] for row in out["players"]
    )
    assert (
        out["stage2_lineage_contract"]
        == "V12_CANONICAL_STAGE2_SINGLE_CHAIN_V1"
    )
    assert out["stage2_lineage_complete_players"] == len(out["players"])
    assert all(
        (row["stage2_lineage"] or {}).get("lineage_complete") is True
        for row in out["players"]
    )
    assert all(
        (row["stage2_lineage"]["p1_1"] or {}).get("owner")
        == "V12_PLAYER_MINUTES"
        for row in out["players"]
    )
    assert all(
        (row["stage2_lineage"]["posterior"] or {}).get("owner")
        == "V12_PLAYER_EVENTS"
        for row in out["players"]
    )
    assert out["new_xpts_model_created"] is False
    assert out["new_xmins_model_created"] is False



def _normalized_history(source_id, rows, *, missing_gws=None):
    return {
        "source_id": source_id,
        "source_health": "GREEN",
        "normalization_status": "NORMALIZED",
        "effective_at": "2026-09-21T14:00:00Z",
        "source_snapshot_ids": [source_id + ":snapshot"],
        "normalization_version": "test",
        "history_coverage": {
            "finished_gws": [1, 2, 3],
            "available_gws": sorted({row["gw"] for row in rows}),
            "missing_gws": list(missing_gws or []),
        },
        "record_groups": {"player_matches": rows},
    }


def _foundation_rows(max_gw=3):
    rows = []
    for gw in range(1, max_gw + 1):
        rows.extend(
            [
                {
                    "official_element_id": 1,
                    "identity_status": "EXACT",
                    "official_fixture_id": 100 + gw,
                    "fixture_identity_status": "EXACT",
                    "official_opponent_team_id": 2,
                    "opponent_identity_status": "EXACT",
                    "gw": gw,
                    "position": "MID",
                    "team_id": 1,
                    "minutes": 90,
                    "starter": True,
                    "home": gw % 2 == 1,
                    "fpl_points": 5 + gw,
                    "goals": 0,
                    "assists": 1 if gw == 2 else 0,
                    "xg": 0.20 + 0.03 * gw,
                    "xa": 0.12,
                    "xgi": 0.32 + 0.03 * gw,
                    "xgc": 0.8,
                    "clean_sheets": 0,
                    "goals_conceded": 1,
                    "saves": 0,
                    "penalties_saved": 0,
                    "penalties_missed": 0,
                    "bonus": 1,
                    "bps": 18,
                    "defensive": 5,
                    "clearances_blocks_interceptions": 2,
                    "recoveries": 4,
                    "tackles": 1,
                    "source": "official_fpl",
                    "dataset": "event_live",
                },
                {
                    "official_element_id": 2,
                    "identity_status": "EXACT",
                    "official_fixture_id": 200 + gw,
                    "fixture_identity_status": "EXACT",
                    "official_opponent_team_id": 1,
                    "opponent_identity_status": "EXACT",
                    "gw": gw,
                    "position": "FWD",
                    "team_id": 2,
                    "minutes": 80,
                    "starter": True,
                    "home": gw % 2 == 0,
                    "fpl_points": 4 + gw,
                    "goals": 1 if gw == 3 else 0,
                    "assists": 0,
                    "xg": 0.35,
                    "xa": 0.08 + 0.02 * gw,
                    "xgi": 0.43 + 0.02 * gw,
                    "xgc": 1.1,
                    "clean_sheets": 0,
                    "goals_conceded": 1,
                    "saves": 0,
                    "penalties_saved": 0,
                    "penalties_missed": 0,
                    "bonus": 0,
                    "bps": 15,
                    "defensive": 3,
                    "clearances_blocks_interceptions": 1,
                    "recoveries": 3,
                    "tackles": 1,
                    "source": "official_fpl",
                    "dataset": "event_live",
                },
            ]
        )
    return rows


def _foundation_bootstrap():
    return {
        "events": [
            {"id": 1, "finished": True},
            {"id": 2, "finished": True},
            {"id": 3, "finished": True},
            {"id": 4, "finished": False},
        ],
        "elements": [
            {"id": 1, "team": 1, "element_type": 3},
            {"id": 2, "team": 2, "element_type": 4},
        ],
        "teams": [{"id": 1}, {"id": 2}],
    }


def _write_normalized(root, source_id, payload):
    path = root / "data/v6/normalized/sources"
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{source_id}.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_stage1_foundation_prefers_complete_official_history(tmp_path):
    official_rows = _foundation_rows(3)
    stale_mirror = [
        {
            **row,
            "source": "vaastav_fpl",
            "dataset": "merged_gw",
        }
        for row in _foundation_rows(1)
    ]
    _write_normalized(
        tmp_path,
        "official_fpl",
        _normalized_history("official_fpl", official_rows),
    )
    _write_normalized(
        tmp_path,
        "vaastav_fpl",
        _normalized_history(
            "vaastav_fpl",
            stale_mirror,
            missing_gws=[2, 3],
        ),
    )

    out = load_v6_analytics_foundation(
        tmp_path,
        bootstrap=_foundation_bootstrap(),
        planning_gw=4,
        strength=_strength(),
    )
    assert out["status"] == "MATCH_FOUNDATION_READY"
    assert out["stage1_full_foundation_ready"] is True
    assert out["selected_match_source"] == "official_fpl"
    assert (
        out["match_source_selection_reason"]
        == "OFFICIAL_FPL_COMPLETE_PRIMARY"
    )
    assert out["observed_gws"] == [1, 2, 3]
    assert out["blockers"] == []


def test_stage1_foundation_rejects_stale_mirror_fallback(tmp_path):
    stale_rows = [
        {
            **row,
            "source": "vaastav_fpl",
            "dataset": "merged_gw",
        }
        for row in _foundation_rows(1)
    ]
    _write_normalized(
        tmp_path,
        "vaastav_fpl",
        _normalized_history(
            "vaastav_fpl",
            stale_rows,
            missing_gws=[2, 3],
        ),
    )

    out = load_v6_analytics_foundation(
        tmp_path,
        bootstrap=_foundation_bootstrap(),
        planning_gw=4,
        strength=_strength(),
    )
    assert out["status"] == "BLOCKED"
    assert out["stage1_full_foundation_ready"] is False
    assert "NO_COMPLETE_MATCH_HISTORY_SOURCE" in out["blockers"]
    assert out["match_source_candidates"]["vaastav_fpl"]["max_gw"] == 1

from src.models.v12_multiwindow_form import (
    build_multiwindow_form_snapshot,
    build_player_multiwindow_form,
)


def _mw_row(
    gw,
    *,
    player_id=9001,
    minutes=90,
    starter=True,
    goals=0,
    assists=0,
    xg=0.30,
    npxg=0.30,
    xa=0.20,
    xgi=None,
    shots=3,
    shots_in_box=2,
    shots_on_target=1,
    box_touches=6,
    key_passes=2,
    chances_created=2,
    source="synthetic_provider",
):
    return {
        "player_id": player_id,
        "element": player_id,
        "gw": gw,
        "match_id": 90000 + gw,
        "minutes": minutes,
        "starter": starter,
        "goals": goals,
        "assists": assists,
        "xg": xg,
        "npxg": npxg,
        "xa": xa,
        "xgi": xg + xa if xgi is None else xgi,
        "shots": shots,
        "shots_in_box": shots_in_box,
        "shots_on_target": shots_on_target,
        "box_touches": box_touches,
        "key_passes": key_passes,
        "chances_created": chances_created,
        "source": source,
        "freshness": "2026-09-25T02:00:00Z",
        "season": "2026/27",
    }


def test_multiwindow_five_full_starts_and_exact_windows():
    rows = [_mw_row(gw) for gw in range(1, 6)]
    out = build_player_multiwindow_form(rows, player_id=9001)
    assert out["windows"]["MATCH"]["sample_matches"] == 1
    assert out["windows"]["L3"]["sample_matches"] == 3
    assert out["windows"]["L5"]["sample_matches"] == 5
    assert out["windows"]["SEASON"]["sample_matches"] == 5
    assert out["windows"]["L5"]["sample_minutes"] == 450.0
    assert out["windows"]["L5"]["derived"]["start_share"]["value"] == 1.0


def test_multiwindow_less_than_five_matches_is_sample_aware():
    out = build_player_multiwindow_form([_mw_row(1), _mw_row(2)])
    assert out["windows"]["L5"]["sample_matches"] == 2
    assert out["windows"]["SEASON"]["confidence"]["label"] != "MATURE"
    assert out["signals"]["sample_eligibility"]["eligible"] is False


def test_multiwindow_mixed_starts_and_subs():
    rows = [
        _mw_row(1, minutes=90, starter=True),
        _mw_row(2, minutes=30, starter=False),
        _mw_row(3, minutes=15, starter=False),
    ]
    out = build_player_multiwindow_form(rows)
    l3 = out["windows"]["L3"]
    assert l3["sample_minutes"] == 135.0
    assert l3["metrics"]["starts"]["value"] == 1.0
    assert l3["derived"]["start_share"]["value"] == round(1 / 3, 6)


def test_multiwindow_zero_minute_event_is_not_a_statistical_match():
    rows = [_mw_row(1), _mw_row(2, minutes=0), _mw_row(3)]
    out = build_player_multiwindow_form(rows)
    assert out["excluded_zero_or_missing_minute_rows"] == 1
    assert out["windows"]["SEASON"]["sample_matches"] == 2
    assert [x["gw"] for x in out["windows"]["SEASON"]["match_refs"]] == [1, 3]


def test_multiwindow_missing_xa_and_npxg_remain_missing():
    rows = [
        _mw_row(1, xa=None, npxg=None, xgi=0.30),
        _mw_row(2, xa=None, npxg=None, xgi=0.35),
        _mw_row(3, xa=None, npxg=None, xgi=0.40),
    ]
    out = build_player_multiwindow_form(rows)
    season = out["windows"]["SEASON"]["metrics"]
    assert season["xa"]["value"] is None
    assert season["xa"]["availability"] == "UNAVAILABLE"
    assert season["npxg"]["value"] is None
    assert out["regression"]["SEASON"]["goals_minus_npxg"]["value"] is None


def test_multiwindow_provider_mismatch_fails_closed():
    rows = [
        _mw_row(1, source="provider_a"),
        _mw_row(2, source="provider_b"),
    ]
    out = build_player_multiwindow_form(rows)
    assert out["status"] == "PROVIDER_MISMATCH"
    assert out["provider_guard"]["aggregation_allowed"] is False
    assert out["windows"] == {}


def test_multiwindow_exact_boundary_uses_latest_played_appearances():
    out = build_player_multiwindow_form([_mw_row(gw) for gw in range(1, 7)])
    assert [x["gw"] for x in out["windows"]["MATCH"]["match_refs"]] == [6]
    assert [x["gw"] for x in out["windows"]["L3"]["match_refs"]] == [4, 5, 6]
    assert [x["gw"] for x in out["windows"]["L5"]["match_refs"]] == [2, 3, 4, 5, 6]


def test_multiwindow_partial_metric_is_not_zero_filled():
    rows = [_mw_row(gw) for gw in range(1, 4)]
    rows[1]["shots"] = None
    out = build_player_multiwindow_form(rows)
    shots = out["windows"]["L3"]["metrics"]["shots"]
    assert shots["availability"] == "PARTIAL"
    assert shots["value"] is None
    assert shots["missing_matches"] == 1


def test_multiwindow_output_is_deterministic():
    rows = [_mw_row(gw) for gw in range(1, 6)]
    first = build_multiwindow_form_snapshot(rows, season="2026/27")
    second = build_multiwindow_form_snapshot(list(reversed(rows)), season="2026/27")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_multiwindow_metric_and_derived_provenance_contract():
    out = build_player_multiwindow_form([_mw_row(gw) for gw in range(1, 6)])
    raw = out["windows"]["L3"]["metrics"]["xgi"]["provenance"]
    derived = out["comparisons"]["L3"]["xgi"]["delta_vs_season"]["provenance"]
    for provenance in (raw, derived):
        for field in (
            "provider",
            "retrieved_at",
            "season",
            "gw_match",
            "metric_name",
            "metric_definition",
            "window",
            "raw_or_derived",
            "sample_minutes",
            "sample_matches",
            "confidence",
            "availability",
        ):
            assert field in provenance
    assert raw["provider"] == "synthetic_provider"
    assert raw["season"] == "2026/27"


def test_positive_regression_watch_four_blanks_with_strong_xgi():
    rows = [
        _mw_row(gw, goals=0, assists=0, xg=0.40, xa=0.25, xgi=0.65)
        for gw in range(1, 5)
    ]
    out = build_player_multiwindow_form(rows)
    signal = out["signals"]["POSITIVE_REGRESSION_WATCH"]
    assert signal["sample_eligible"] is True
    assert signal["active"] is True
    assert "no rebound is guaranteed" in signal["reasons"]


def test_negative_regression_watch_high_returns_weak_underlying():
    rows = [
        _mw_row(
            gw, goals=1, assists=0, xg=0.08, npxg=0.08, xa=0.02,
            xgi=0.10, shots=1, shots_in_box=1, shots_on_target=1,
        )
        for gw in range(1, 6)
    ]
    out = build_player_multiwindow_form(rows)
    assert out["signals"]["NEGATIVE_REGRESSION_WATCH"]["active"] is True


def test_breakout_requires_recent_underlying_and_supporting_volume():
    rows = [
        _mw_row(
            gw, xg=0.10, npxg=0.10, xa=0.05, xgi=0.15,
            shots=1, shots_in_box=1, shots_on_target=0, box_touches=2,
            key_passes=1, chances_created=1,
        )
        for gw in range(1, 4)
    ] + [
        _mw_row(
            gw, xg=0.40, npxg=0.40, xa=0.20, xgi=0.60,
            shots=4, shots_in_box=3, shots_on_target=2, box_touches=9,
            key_passes=3, chances_created=3,
        )
        for gw in range(4, 7)
    ]
    out = build_player_multiwindow_form(rows)
    assert out["signals"]["BREAKOUT"]["active"] is True


def test_low_sample_does_not_raise_breakout_or_regression_signal():
    rows = [
        _mw_row(1, xg=0.8, xa=0.5, xgi=1.3, shots=7),
        _mw_row(2, xg=0.9, xa=0.5, xgi=1.4, shots=8),
    ]
    out = build_player_multiwindow_form(rows)
    assert out["signals"]["sample_eligibility"]["eligible"] is False
    for key in (
        "POSITIVE_REGRESSION_WATCH",
        "NEGATIVE_REGRESSION_WATCH",
        "BREAKOUT",
        "ROLE_DECLINE",
    ):
        assert out["signals"][key]["active"] is False


def test_role_decline_uses_minutes_security_plus_underlying_decline():
    rows = [
        _mw_row(
            gw, minutes=90, starter=True, xg=0.40, xa=0.20,
            xgi=0.60, shots=4,
        )
        for gw in range(1, 4)
    ] + [
        _mw_row(
            gw, minutes=60, starter=False, xg=0.10, xa=0.05,
            xgi=0.15, shots=1,
        )
        for gw in range(4, 7)
    ]
    out = build_player_multiwindow_form(rows)
    assert out["signals"]["ROLE_DECLINE"]["active"] is True


def test_foundation_feature_disabled_preserves_existing_output_shape(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("V12_MULTIWINDOW_FORM_ENABLED", raising=False)
    _write_normalized(
        tmp_path,
        "official_fpl",
        _normalized_history("official_fpl", _foundation_rows(3)),
    )
    out = load_v6_analytics_foundation(
        tmp_path,
        bootstrap=_foundation_bootstrap(),
        planning_gw=4,
        strength=_strength(),
    )
    assert "multiwindow_underlying_form" not in out


def test_foundation_feature_enabled_exposes_advisory_snapshot_only(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("V12_MULTIWINDOW_FORM_ENABLED", "1")
    _write_normalized(
        tmp_path,
        "official_fpl",
        _normalized_history("official_fpl", _foundation_rows(3)),
    )
    out = load_v6_analytics_foundation(
        tmp_path,
        bootstrap=_foundation_bootstrap(),
        planning_gw=4,
        strength=_strength(),
    )
    snapshot = out["multiwindow_underlying_form"]
    assert snapshot["contract"] == "V12_MULTIWINDOW_FORM_SNAPSHOT_V1"
    assert snapshot["governance"]["decision_math_changed"] is False
    player = snapshot["players"]["1"]
    assert player["windows"]["L3"]["metrics"]["npxg"]["value"] is None
    assert (
        player["windows"]["L3"]["metrics"]["npxg"]["availability"]
        == "UNAVAILABLE"
    )

def test_multiwindow_missing_provider_fails_closed():
    row = _mw_row(1)
    row.pop("source")
    out = build_player_multiwindow_form([row])
    assert out["status"] == "PROVIDER_MISMATCH"
    assert out["provider_guard"]["status"] == "PROVIDER_UNAVAILABLE"
    assert out["provider_guard"]["aggregation_allowed"] is False

