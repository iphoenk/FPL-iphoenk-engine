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
    assert out["status"] == "PROVIDER_UNAVAILABLE"
    assert out["provider_guard"]["status"] == "PROVIDER_UNAVAILABLE"
    assert out["provider_guard"]["aggregation_allowed"] is False

from copy import deepcopy

from src.engines.v12_stageb_ab import (
    apply_existing_p11_availability_overlay,
    compare_player_ordering,
    compare_transfer_comparator_outputs,
    run_exact_p17_ab,
    shadow_component_replacement,
)
from src.engines.v12_lineup_optimizer import optimize_lineup
from src.models.v12_stageb_evidence import (
    attach_stageb_shadow_evidence,
    build_availability_state,
    build_defcon_probability,
    build_role_duty_evidence,
)


def _stageb_xmins(*, expected=82.0, low=70.0, high=90.0):
    return {
        "expected_minutes": expected,
        "expected_minutes_interval": [low, high],
        "minutes_std": max(1.0, (high - low) / 2.56),
        "start_probability": 0.9,
        "confidence": "HIGH",
        "xmins_distribution": {
            "distribution": "FINITE_STATE_MINUTES_MIXTURE",
            "states": [
                {"state": "START_FULL", "probability": 0.8, "minutes_mean": 90},
                {"state": "START_SUBBED", "probability": 0.1, "minutes_mean": 70},
                {"state": "CAMEO", "probability": 0.05, "minutes_mean": 20},
                {"state": "DNP", "probability": 0.05, "minutes_mean": 0},
            ],
        },
    }


def _stageb_def_row(
    gw,
    defensive,
    *,
    player_id=8101,
    home=True,
    position="DEF",
    opponent=20,
    minutes=90,
    starter=True,
    actual_role=None,
):
    return {
        "player_id": player_id,
        "element": player_id,
        "gw": gw,
        "match_id": 81000 + gw,
        "position": position,
        "opponent_team_id": opponent,
        "home": home,
        "minutes": minutes,
        "starter": starter,
        "defensive": defensive,
        "actual_role": actual_role,
    }


def _stageb_universe_rows():
    rows = []
    for player_id in range(8201, 8205):
        for gw in range(1, 5):
            rows.append(
                _stageb_def_row(
                    gw,
                    10 + (gw % 3),
                    player_id=player_id,
                    home=gw % 2 == 0,
                    position="DEF",
                    opponent=20 if gw <= 3 else 21,
                )
            )
    return rows


def test_stageb_high_defcon_weak_cs_fixture_is_independent_of_cs():
    rows = [_stageb_def_row(gw, 14) for gw in range(1, 7)]
    out = build_defcon_probability(
        player_id=8101,
        element_type=2,
        match_rows=rows,
        universe_rows=_stageb_universe_rows(),
        xmins=_stageb_xmins(),
        target_home=True,
        target_opponent_team_id=20,
        baseline_probability=0.55,
    )
    assert out["defcon_hits"] == 6
    assert out["hit_rate"] == 1.0
    assert out["projected_hit_probability"] > 0.5
    assert out["provenance"]["clean_sheet_used_as_input"] is False
    assert out["governance"]["clean_sheet_defcon_double_count_guard"] is True


def test_stageb_low_defcon_strong_cs_does_not_create_defcon_points():
    rows = [_stageb_def_row(gw, 3) for gw in range(1, 7)]
    out = build_defcon_probability(
        player_id=8101,
        element_type=2,
        match_rows=rows,
        universe_rows=_stageb_universe_rows(),
        xmins=_stageb_xmins(),
        target_home=False,
        target_opponent_team_id=21,
        baseline_probability=0.15,
    )
    assert out["defcon_hits"] == 0
    assert out["hit_rate"] == 0.0
    assert out["DEFCON_EV"] < 1.0
    assert out["provenance"]["clean_sheet_used_as_input"] is False


def test_stageb_home_away_asymmetry_changes_conditioned_probability():
    rows = []
    for gw in range(1, 7):
        rows.append(
            _stageb_def_row(
                gw,
                15 if gw <= 3 else 6,
                home=gw <= 3,
                opponent=20,
            )
        )
    home = build_defcon_probability(
        player_id=8101,
        element_type=2,
        match_rows=rows,
        universe_rows=_stageb_universe_rows(),
        xmins=_stageb_xmins(),
        target_home=True,
        target_opponent_team_id=20,
        baseline_probability=0.4,
    )
    away = build_defcon_probability(
        player_id=8101,
        element_type=2,
        match_rows=rows,
        universe_rows=_stageb_universe_rows(),
        xmins=_stageb_xmins(),
        target_home=False,
        target_opponent_team_id=20,
        baseline_probability=0.4,
    )
    assert home["model"]["venue"]["state"] == "AVAILABLE"
    assert away["model"]["venue"]["state"] == "AVAILABLE"
    assert home["projected_hit_probability"] > away["projected_hit_probability"]


def test_stageb_defcon_under_three_starts_is_low_confidence():
    rows = [_stageb_def_row(1, 12), _stageb_def_row(2, 11)]
    out = build_defcon_probability(
        player_id=8101,
        element_type=2,
        match_rows=rows,
        xmins=_stageb_xmins(),
        baseline_probability=0.4,
    )
    assert out["eligible_starts"] == 2
    assert out["confidence"] == "LOW"
    assert out["model"]["venue"]["state"] == "UNAVAILABLE_OR_LOW_SAMPLE"


def test_stageb_xmins_uncertainty_is_published_and_downgrades_confidence():
    rows = [_stageb_def_row(gw, 12) for gw in range(1, 7)]
    out = build_defcon_probability(
        player_id=8101,
        element_type=2,
        match_rows=rows,
        universe_rows=_stageb_universe_rows(),
        xmins=_stageb_xmins(expected=50, low=10, high=90),
        target_opponent_team_id=20,
        baseline_probability=0.5,
    )
    assert out["model"]["xmins_uncertainty"]["label"] == "LOW"
    assert out["confidence"] != "HIGH"
    assert out["model"]["xmins_mode"] == "FINITE_STATE_DISTRIBUTION"


def test_stageb_international_unavailable_reason_unknown_is_not_injury():
    out = build_availability_state(
        [
            {
                "source": "news-wire",
                "timestamp": "2026-09-25T01:00:00Z",
                "evidence_type": "NEWS_REPORT",
                "confidence": 0.7,
                "availability": "UNAVAILABLE",
                "reason": "not selected; reason not stated",
                "state_hint": "INJURED",
            }
        ],
        as_of="2026-09-25T04:00:00Z",
    )
    assert out["state"] == "UNAVAILABLE_UNKNOWN"
    assert out["active_evidence"][0]["diagnosis_inferred"] is False
    assert out["governance"]["unknown_unavailability_is_not_injury"] is True


def test_stageb_played_90_international_minutes_is_heavy_minutes():
    out = build_availability_state(
        [
            {
                "source": "official-international-match",
                "timestamp": "2026-09-24T20:00:00Z",
                "evidence_type": "INTERNATIONAL_APPEARANCE",
                "confidence": 1.0,
                "minutes": 90,
            }
        ],
        as_of="2026-09-25T04:00:00Z",
    )
    assert out["state"] == "INTERNATIONAL_HEAVY_MINUTES"
    assert (
        out["xmins_context_overlay"]["application"]
        == "EXISTING_P1_1_CONGESTION_FACTOR"
    )
    assert out["xmins_context_overlay"]["congestion_factor"] < 1.0
    assert (
        out["xmins_context_overlay"]["calibration_status"]
        == "EXPERIMENTAL_BOUNDED_AB_ONLY_NOT_EMPIRICALLY_CALIBRATED"
    )
    assert (
        out["governance"]["numeric_congestion_overlay_is_model_assumption_not_fact"]
        is True
    )


def test_stageb_club_available_does_not_erase_heavy_international_workload():
    out = build_availability_state(
        [
            {
                "source": "club-statement",
                "timestamp": "2026-09-25T02:00:00Z",
                "evidence_type": "CLUB_STATEMENT",
                "confidence": 0.95,
                "availability": "AVAILABLE",
            },
            {
                "source": "official-international-match",
                "timestamp": "2026-09-24T20:00:00Z",
                "evidence_type": "INTERNATIONAL_APPEARANCE",
                "confidence": 1.0,
                "minutes": 90,
            },
        ],
        as_of="2026-09-25T04:00:00Z",
    )
    assert out["state"] == "CLUB_CONFIRMED_AVAILABLE"
    assert "INTERNATIONAL_HEAVY_MINUTES" in out["secondary_workload_states"]
    assert out["xmins_context_overlay"]["congestion_factor"] < 1.0


def test_stageb_conflicting_confirmed_sources_fail_to_doubt():
    out = build_availability_state(
        [
            {
                "source": "official-status",
                "timestamp": "2026-09-25T02:00:00Z",
                "evidence_type": "OFFICIAL_STATUS",
                "confidence": 0.95,
                "availability": "UNAVAILABLE",
            },
            {
                "source": "club-statement",
                "timestamp": "2026-09-25T02:30:00Z",
                "evidence_type": "CLUB_STATEMENT",
                "confidence": 0.95,
                "availability": "AVAILABLE",
            },
        ],
        as_of="2026-09-25T04:00:00Z",
    )
    assert out["state"] == "DOUBT"
    assert out["conflicting_sources"] is True
    assert out["confidence"] <= 0.5
    assert out["xmins_context_overlay"]["availability_probability_override"] is None


def test_stageb_stale_availability_cannot_drive_state():
    out = build_availability_state(
        [
            {
                "source": "old-news",
                "timestamp": "2026-09-20T00:00:00Z",
                "evidence_type": "NEWS_REPORT",
                "confidence": 0.9,
                "availability": "UNAVAILABLE",
            }
        ],
        as_of="2026-09-25T04:00:00Z",
    )
    assert out["state"] == "FIT"
    assert out["active_evidence"] == []
    assert len(out["stale_evidence"]) == 1


def test_stageb_role_facts_cannot_be_overwritten_by_external_opinion():
    official = {
        "id": 8101,
        "element_type": 2,
        "penalties_order": 1,
        "penalties_text": "First choice",
        "corners_and_indirect_freekicks_order": 2,
        "corners_and_indirect_freekicks_text": "Second choice",
        "direct_freekicks_order": 3,
        "direct_freekicks_text": "Third choice",
    }
    rows = [
        _stageb_def_row(gw, 10, starter=gw != 5, minutes=70 if gw == 4 else 90)
        for gw in range(1, 6)
    ]
    out = build_role_duty_evidence(
        official_player=official,
        match_rows=rows,
        xmins=_stageb_xmins(),
        tactical_role={
            "profile": "OVERLAPPING_FULLBACK",
            "confidence": "MEDIUM",
            "source": "observed-role",
        },
        external_claims=[
            {
                "source": "analyst",
                "claim_type": "penalty_duty",
                "value": "not on penalties",
                "confidence": 0.9,
            }
        ],
    )
    assert out["FACT"]["penalty_duty"]["value"]["order"] == 1
    assert out["FACT"]["penalty_duty"]["class"] == "FACT"
    assert out["DERIVED"]["actual_tactical_role"]["value"] == "OVERLAPPING_FULLBACK"
    assert out["INFERRED"][0]["authoritative_override"] is False


def test_stageb_feature_off_is_exact_noop():
    payload = {
        "planning_gw": 6,
        "players": [{"element": 8101, "xmins": _stageb_xmins()}],
    }
    before = deepcopy(payload)
    returned = attach_stageb_shadow_evidence(
        payload,
        bootstrap={"elements": [{"id": 8101, "element_type": 2}]},
        match_rows=[_stageb_def_row(1, 12)],
        enabled=False,
    )
    assert returned is payload
    assert payload == before


def test_stageb_existing_p11_owner_consumes_heavy_minutes_via_congestion_only():
    availability = build_availability_state(
        [
            {
                "source": "official-international-match",
                "timestamp": "2026-09-24T20:00:00Z",
                "evidence_type": "INTERNATIONAL_APPEARANCE",
                "confidence": 1.0,
                "minutes": 90,
            }
        ],
        as_of="2026-09-25T04:00:00Z",
    )
    player = {
        "id": 8101,
        "status": "a",
        "chance_of_playing_next_round": 100,
        "starts": 5,
        "minutes": 430,
    }
    out = apply_existing_p11_availability_overlay(
        player=player,
        baseline_context={"team_matches_played": 5},
        availability_state=availability,
    )
    assert out["owner"] == "V12_PLAYER_MINUTES"
    assert out["new_minutes_owner_created"] is False
    assert out["causal_field"] == "context.congestion_factor"
    assert out["enriched"]["expected_minutes"] < out["baseline"]["expected_minutes"]
    assert out["enriched"]["start_probability"] < out["baseline"]["start_probability"]


def test_stageb_defcon_ev_replaces_not_adds_baseline_component():
    out = shadow_component_replacement(
        baseline_total=6.0,
        baseline_components={
            "attacking": 1.5,
            "clean_sheet": 2.0,
            "defensive_contribution": 0.8,
            "bonus": 0.5,
        },
        enriched_defcon_ev=1.4,
    )
    assert out["shadow_total"] == 6.6
    assert out["delta"] == 0.6
    assert out["double_count_guard"] is True
    assert out["causal_field"] == "DEFCON_EV_REPLACEMENT"


def _stageb_pmf(meanish):
    return {
        "0": 0.10,
        str(max(3, int(round(meanish)))): 0.70,
        str(max(8, int(round(meanish + 4)))): 0.20,
    }


def _stageb_projection(element, position, meanish):
    probs = _stageb_pmf(meanish)
    mean = sum(int(points) * probability for points, probability in probs.items())
    second = sum(int(points) ** 2 * probability for points, probability in probs.items())
    variance = max(0.0, second - mean * mean)
    return {
        "element": element,
        "name": f"B{element}",
        "position": position,
        "team_id": (element % 10) + 1,
        "projection_confidence": "HIGH",
        "xmins": {
            "start_probability": 0.9,
            "cameo_probability": 0.04,
            "late_cameo_probability": 0.01,
            "dnp_probability": 0.06,
            "availability": 0.94,
            "expected_minutes": 82.0,
            "confidence": "HIGH",
            "xmins_distribution": {
                "distribution": "FINITE_STATE_MINUTES_MIXTURE",
                "mean": 82.0,
                "std": 12.0,
                "states": [
                    {"state": "START_FULL", "probability": 0.9, "minutes_mean": 90, "minutes_std": 0},
                    {"state": "CAMEO", "probability": 0.03, "minutes_mean": 18, "minutes_std": 0},
                    {"state": "LATE_CAMEO", "probability": 0.01, "minutes_mean": 7, "minutes_std": 0},
                    {"state": "DNP", "probability": 0.06, "minutes_mean": 0, "minutes_std": 0},
                ],
            },
        },
        "tactical_role_component": {
            "canonical_tactical_role_score": 60.0,
            "confidence": 0.9,
            "canonical_component": {
                "name": "TACTICAL_ROLE",
                "weight": 0.25,
                "weighted_component_points": 15.0,
            },
        },
        "xpts_by_gw": [
            {
                "gw": 6,
                "mean": mean,
                "std": variance ** 0.5,
                "points_variance": variance,
                "point_distribution": {
                    "model": "FINITE_STATE_CONDITIONAL_CORE_POINT_PMF_V1",
                    "distribution_completeness": "PARTIAL_BONUS_RESIDUAL",
                    "bonus_incorporation": "EXPECTATION_ONLY_NOT_STOCHASTIC",
                    "probabilities": probs,
                },
                "fixtures": [],
            }
        ],
    }


def _stageb_squad():
    positions = ["GK", "GK"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    means = [4.8, 3.9, 5.4, 5.2, 5.0, 4.7, 3.0, 7.4, 7.0, 6.4, 5.8, 4.6, 8.1, 6.7, 5.9]
    return {
        "planning_gw": 6,
        "players": [
            _stageb_projection(index + 1, position, means[index])
            for index, position in enumerate(positions)
        ],
    }


def test_stageb_controlled_exact_p17_ab_reports_xi_bench_captain_vice():
    baseline = _stageb_squad()
    squad_ids = [row["element"] for row in baseline["players"]]
    baseline_decision = optimize_lineup(
        baseline,
        squad_ids,
        planning_gw=6,
        generated_at="2026-09-25T04:00:00Z",
    )
    bench_ids = [
        int(row["element"])
        for row in baseline_decision["bench"]["order"]
        if row.get("position") != "GK"
    ]
    assert bench_ids
    target = bench_ids[0]
    enriched = deepcopy(baseline)
    replacement = next(row for row in enriched["players"] if row["element"] == target)
    boosted = _stageb_projection(target, replacement["position"], 30.0)
    replacement.clear()
    replacement.update(boosted)

    out = run_exact_p17_ab(
        baseline_projections=baseline,
        enriched_projections=enriched,
        squad_ids=squad_ids,
        planning_gw=6,
        generated_at="2026-09-25T04:00:00Z",
    )
    assert out["p17_semantics_changed"] is False
    assert set(out["changed"]) == {"XI", "bench", "captain", "vice", "formation"}
    assert out["changed"]["XI"] is True
    assert out["changed"]["bench"] is True
    assert out["changed"]["captain"] is True
    assert out["changed"]["vice"] is True


def test_stageb_player_ordering_and_transfer_comparator_ab_are_diagnostic_only():
    ordering = compare_player_ordering(
        [{"element": 1, "score": 5.0}, {"element": 2, "score": 4.0}],
        [{"element": 1, "score": 5.0}, {"element": 2, "score": 5.5}],
    )
    comparator = compare_transfer_comparator_outputs(
        {
            "comparisons": [
                {"candidate": {"element": 2}, "raw_gains": {"1": -0.2, "3": 0.4}}
            ]
        },
        {
            "comparisons": [
                {"candidate": {"element": 2}, "raw_gains": {"1": 0.3, "3": 0.9}}
            ]
        },
    )
    assert ordering["changed"] is True
    assert ordering["baseline"] == [1, 2]
    assert ordering["enriched"] == [2, 1]
    assert comparator["changed"] is True
    assert comparator["comparator_semantics_changed"] is False
    assert comparator["ranking_authority_created"] is False

def test_stageb_evidence_outputs_are_deterministic():
    rows = [
        _stageb_def_row(
            gw,
            12 + (gw % 2),
            home=gw % 2 == 1,
            opponent=20 if gw <= 3 else 21,
            actual_role="OVERLAPPING_FULLBACK",
        )
        for gw in range(1, 7)
    ]
    kwargs = {
        "player_id": 8101,
        "element_type": 2,
        "match_rows": rows,
        "universe_rows": _stageb_universe_rows(),
        "xmins": _stageb_xmins(),
        "target_home": True,
        "target_opponent_team_id": 20,
        "target_role": "OVERLAPPING_FULLBACK",
        "baseline_probability": 0.4,
    }
    assert build_defcon_probability(**kwargs) == build_defcon_probability(**kwargs)

    availability_evidence = [
        {
            "source": "club-statement",
            "timestamp": "2026-09-25T02:00:00Z",
            "evidence_type": "CLUB_STATEMENT",
            "confidence": 0.95,
            "availability": "AVAILABLE",
        },
        {
            "source": "official-international-match",
            "timestamp": "2026-09-24T20:00:00Z",
            "evidence_type": "INTERNATIONAL_APPEARANCE",
            "confidence": 1.0,
            "minutes": 90,
        },
    ]
    assert build_availability_state(
        availability_evidence,
        as_of="2026-09-25T04:00:00Z",
    ) == build_availability_state(
        availability_evidence,
        as_of="2026-09-25T04:00:00Z",
    )

    official = {
        "id": 8101,
        "element_type": 2,
        "penalties_order": 1,
        "corners_and_indirect_freekicks_order": 2,
        "direct_freekicks_order": 3,
    }
    role_kwargs = {
        "official_player": official,
        "match_rows": rows,
        "xmins": _stageb_xmins(),
        "tactical_role": {
            "profile": "OVERLAPPING_FULLBACK",
            "confidence": "MEDIUM",
            "source": "observed-role",
        },
    }
    assert build_role_duty_evidence(**role_kwargs) == build_role_duty_evidence(**role_kwargs)

def test_stageb_reconstructs_official_cbit_cbirt_without_zero_fill():
    defender_rows = [
        {
            "player_id": 8301,
            "element": 8301,
            "gw": gw,
            "match_id": 83000 + gw,
            "position": "DEF",
            "opponent_team_id": 20,
            "home": True,
            "minutes": 90,
            "starter": True,
            "clearances_blocks_interceptions": 8,
            "tackles": 2,
        }
        for gw in range(1, 4)
    ]
    defender = build_defcon_probability(
        player_id=8301,
        element_type=2,
        match_rows=defender_rows,
        xmins=_stageb_xmins(),
        baseline_probability=0.3,
    )
    assert defender["eligible_starts"] == 3
    assert defender["defcon_hits"] == 3
    assert defender["def_actions_per90"] == 10.0

    midfielder_rows = [
        {
            "player_id": 8302,
            "element": 8302,
            "gw": gw,
            "match_id": 83100 + gw,
            "position": "MID",
            "opponent_team_id": 20,
            "home": False,
            "minutes": 90,
            "starter": True,
            "clearances_blocks_interceptions": 6,
            "tackles": 2,
            "recoveries": 4,
        }
        for gw in range(1, 4)
    ]
    midfielder = build_defcon_probability(
        player_id=8302,
        element_type=3,
        match_rows=midfielder_rows,
        xmins=_stageb_xmins(),
        baseline_probability=0.3,
    )
    assert midfielder["eligible_starts"] == 3
    assert midfielder["defcon_hits"] == 3
    assert midfielder["def_actions_per90"] == 12.0

    missing_recoveries = [{**row, "recoveries": None} for row in midfielder_rows]
    degraded = build_defcon_probability(
        player_id=8302,
        element_type=3,
        match_rows=missing_recoveries,
        xmins=_stageb_xmins(),
        baseline_probability=0.3,
    )
    assert degraded["eligible_starts"] == 0
    assert degraded["hit_rate"] is None

from src.engines.v12_report_orchestration import render_deep_text
from src.engines.v12_stagec_reporting import (
    attach_stagec_to_deep_report,
    build_stagec_report_surface,
)
from src.models.v12_external_challenge import (
    ExternalChallengeError,
    build_external_challenge_layer,
    challenge_external_claim,
)
from src.models.v12_stagec_universe_scanner import build_universe_scan


def _stagec_projection(
    element,
    *,
    position="MID",
    price=60,
    ownership=5.0,
    xmins=82.0,
    p_start=0.9,
    h1=5.0,
    h2=10.0,
    h3=15.0,
    h5=24.0,
    defcon_ev=None,
    defcon_p=None,
):
    element_type = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}[position]
    stageb = {
        "role_duty": {
            "DERIVED": {
                "actual_tactical_role": {
                    "class": "DERIVED",
                    "value": "ADVANCED_ROLE",
                    "source": "synthetic",
                }
            },
            "FACT": {
                "nominal_position": {
                    "class": "FACT",
                    "value": position,
                    "source": "OFFICIAL_FPL_BOOTSTRAP",
                }
            },
        }
    }
    if defcon_ev is not None or defcon_p is not None:
        stageb["defcon"] = {
            "DEFCON_EV": defcon_ev,
            "projected_hit_probability": defcon_p,
            "hit_rate": 0.5,
            "eligible_starts": 6,
            "confidence": "MODERATE",
        }
    return {
        "element": element,
        "name": f"C{element}",
        "team_id": (element % 20) + 1,
        "position": position,
        "element_type": element_type,
        "now_cost": price,
        "ownership_pct": ownership,
        "xmins": {
            "expected_minutes": xmins,
            "start_probability": p_start,
            "dnp_probability": max(0.0, 1.0 - p_start),
            "confidence": "HIGH",
        },
        "horizons": {
            "1": {"mean": h1},
            "2": {"mean": h2},
            "3": {"mean": h3},
            "5": {"mean": h5},
        },
        "tactical_role": {
            "profile": "ADVANCED_ROLE",
            "confidence": "MEDIUM",
        },
        "stageb_evidence": stageb,
    }


def _stagec_breakout_rows(element):
    rows = []
    for gw in range(1, 7):
        recent = gw >= 4
        rows.append(
            _mw_row(
                gw,
                player_id=element,
                goals=0,
                assists=0,
                xg=0.40 if recent else 0.10,
                npxg=0.40 if recent else 0.10,
                xa=0.20 if recent else 0.05,
                xgi=0.60 if recent else 0.15,
                shots=4 if recent else 1,
                shots_in_box=3 if recent else 1,
                shots_on_target=2 if recent else 0,
                box_touches=9 if recent else 3,
                key_passes=3 if recent else 1,
                chances_created=3 if recent else 1,
            )
        )
    return rows


def _stagec_negative_regression_rows(element):
    return [
        _mw_row(
            gw,
            player_id=element,
            goals=1 if gw >= 4 else 0,
            assists=0,
            xg=0.15,
            npxg=0.15,
            xa=0.05,
            xgi=0.20,
            shots=1,
            shots_in_box=1,
            shots_on_target=1,
            box_touches=3,
            key_passes=1,
            chances_created=1,
        )
        for gw in range(1, 7)
    ]


def _stagec_scan(rows_by_player, projections):
    rows = [
        row
        for group in rows_by_player
        for row in group
    ]
    snapshot = build_multiwindow_form_snapshot(rows, season="2026/27")
    return build_universe_scan(
        projections={"players": projections},
        multiwindow_snapshot=snapshot,
    )


def test_stagec_breakout_before_returns_and_hidden_gem():
    element = 9201
    scan = _stagec_scan(
        [_stagec_breakout_rows(element)],
        [_stagec_projection(element, ownership=3.0, price=55)],
    )
    row = scan["material_candidates"][0]
    assert row["actual_returns"]["L3"]["goal_involvements"] == 0
    assert row["signals"]["BREAKOUT"]["active"] is True
    assert row["signals"]["POSITIVE_REGRESSION"]["active"] is True
    assert row["hidden_gem"] is True
    assert row["positive_signals"]


def test_stagec_false_breakout_low_sample_is_rejected():
    element = 9202
    rows = [
        _mw_row(
            gw,
            player_id=element,
            xg=0.6,
            npxg=0.6,
            xa=0.2,
            xgi=0.8,
            shots=5,
            shots_in_box=4,
        )
        for gw in (1, 2)
    ]
    scan = _stagec_scan(
        [rows],
        [_stagec_projection(element)],
    )
    row = next(x for x in scan["material_candidates"] if x["element"] == element) if scan["material_candidates"] else None
    if row is not None:
        assert row["signals"]["BREAKOUT"]["active"] is False
    form = build_player_multiwindow_form(rows, player_id=element)
    assert form["signals"]["sample_eligibility"]["eligible"] is False
    assert form["signals"]["BREAKOUT"]["active"] is False


def test_stagec_negative_regression_high_points_weak_underlying():
    element = 9203
    scan = _stagec_scan(
        [_stagec_negative_regression_rows(element)],
        [_stagec_projection(element, h1=9, h2=17, h3=24, h5=35)],
    )
    row = next(x for x in scan["material_candidates"] if x["element"] == element)
    assert row["actual_returns"]["L3"]["goal_involvements"] == 3
    assert row["signals"]["NEGATIVE_REGRESSION"]["active"] is True
    assert row["negative_signals"] == ["NEGATIVE_REGRESSION"]
    assert row["underlying"]["L3"]["xgi"]["per90"] == 0.2


def test_stagec_defender_defcon_candidate_is_independent_signal():
    element = 9204
    rows = [
        _mw_row(
            gw,
            player_id=element,
            xg=0.03,
            npxg=0.03,
            xa=0.04,
            xgi=0.07,
            shots=1,
            shots_in_box=1,
            box_touches=2,
        )
        for gw in range(1, 7)
    ]
    scan = _stagec_scan(
        [rows],
        [
            _stagec_projection(
                element,
                position="DEF",
                price=45,
                ownership=4,
                defcon_ev=1.25,
                defcon_p=0.63,
            )
        ],
    )
    row = next(x for x in scan["material_candidates"] if x["element"] == element)
    assert row["signals"]["DEFCON_VALUE"]["active"] is True
    assert row["defcon"]["DEFCON_EV"] == 1.25
    assert "DEFCON_VALUE" in row["positive_signals"]


def test_stagec_external_buy_contradicted_and_sell_agreed():
    element = 9205
    scan = _stagec_scan(
        [_stagec_negative_regression_rows(element)],
        [_stagec_projection(element)],
    )
    buy = challenge_external_claim(
        {
            "source": "AI FPL Manager",
            "timestamp": "2026-09-25T05:00:00Z",
            "element": element,
            "player": f"C{element}",
            "stance": "BUY",
            "rationale_tags": ["FORM"],
            "raw_reference": "manual-capture-1",
        },
        scan=scan,
    )
    sell = challenge_external_claim(
        {
            "source": "FPL GOAT",
            "timestamp": "2026-09-25T05:01:00Z",
            "element": element,
            "player": f"C{element}",
            "stance": "SELL",
            "rationale_tags": ["UNDERLYING"],
            "raw_reference": "manual-capture-2",
        },
        scan=scan,
    )
    assert buy["model_challenge"]["result"] == "DISAGREE"
    assert sell["model_challenge"]["result"] == "AGREE"
    assert buy["predicted_points_adjustment"] == 0.0
    assert sell["ensemble_weight_applied"] is False


def test_stagec_external_no_data_is_explicit():
    scan = {"material_candidates": []}
    out = build_external_challenge_layer([], scan=scan)
    assert out["state"] == "NO_EXTERNAL_DATA"
    assert out["claim_count"] == 0
    assert out["counts"] == {
        "AGREE": 0,
        "DISAGREE": 0,
        "UNRESOLVED": 0,
    }


def test_stagec_xgstat_is_manual_validation_only():
    scan = {"material_candidates": []}
    try:
        challenge_external_claim(
            {
                "source": "xGStat",
                "timestamp": "2026-09-25T05:00:00Z",
                "element": 9206,
                "stance": "WATCH",
                "ingestion_mode": "AUTOMATED",
            },
            scan=scan,
        )
    except ExternalChallengeError as exc:
        assert "MANUAL_VALIDATION_ONLY" in str(exc)
    else:
        raise AssertionError("automated xGStat ingestion must fail closed")

    manual = challenge_external_claim(
        {
            "source": "xGStat",
            "timestamp": "2026-09-25T05:00:00Z",
            "element": 9206,
            "stance": "WATCH",
            "ingestion_mode": "MANUAL_VALIDATION_ONLY",
            "raw_reference": "licensed-or-manual-reference",
        },
        scan=scan,
    )
    assert manual["claim"]["factual_authority"] is False
    assert manual["model_challenge"]["result"] == "UNRESOLVED"


def test_stagec_deterministic_full_universe_scan():
    rows = _stagec_breakout_rows(9207) + _stagec_negative_regression_rows(9208)
    snapshot = build_multiwindow_form_snapshot(rows, season="2026/27")
    projections = {
        "players": [
            _stagec_projection(9207),
            _stagec_projection(9208),
        ]
    }
    first = build_universe_scan(
        projections=projections,
        multiwindow_snapshot=snapshot,
    )
    second = build_universe_scan(
        projections=deepcopy(projections),
        multiwindow_snapshot=deepcopy(snapshot),
    )
    assert first == second
    assert first["full_universe_count"] == 2
    assert all(row["horizons"] == [1, 2, 3, 5] for row in first["evaluation_feed"])
    assert first["governance"]["final_v12_ranking_unchanged"] is True


def test_stagec_667_player_scan_runtime_budget(capsys):
    import time

    breakout_form = build_player_multiwindow_form(
        _stagec_breakout_rows(9997),
        player_id=9997,
        season="2026/27",
    )
    negative_form = build_player_multiwindow_form(
        _stagec_negative_regression_rows(9998),
        player_id=9998,
        season="2026/27",
    )
    neutral_rows = [
        _mw_row(
            gw,
            player_id=9999,
            goals=1 if gw in {3, 6} else 0,
            assists=0,
            xg=0.18,
            npxg=0.18,
            xa=0.07,
            xgi=0.25,
            shots=2,
            shots_in_box=1,
            shots_on_target=1,
            box_touches=5,
            key_passes=1,
            chances_created=1,
        )
        for gw in range(1, 7)
    ]
    neutral_form = build_player_multiwindow_form(
        neutral_rows,
        player_id=9999,
        season="2026/27",
    )

    forms = {}
    projections = []
    for index in range(667):
        element = 10000 + index
        if index < 100:
            template = breakout_form
        elif index < 200:
            template = negative_form
        else:
            template = neutral_form
        forms[str(element)] = {
            **deepcopy(template),
            "player_id": str(element),
        }
        defcon = index >= 200 and index % 10 == 0
        projections.append(
            _stagec_projection(
                element,
                position=("DEF" if index % 4 == 0 else "MID"),
                ownership=float(index % 12),
                price=45 + (index % 30),
                defcon_ev=1.1 if defcon else None,
                defcon_p=0.55 if defcon else None,
            )
        )
    snapshot = {
        "contract": "V12_MULTIWINDOW_FORM_SNAPSHOT_V1",
        "player_count": 667,
        "players": forms,
    }

    started = time.perf_counter()
    scan = build_universe_scan(
        projections={"players": projections},
        multiwindow_snapshot=snapshot,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    with capsys.disabled():
        print(f"STAGEC_667_SCAN_RUNTIME_MS={elapsed_ms:.3f}")
        print(
            "STAGEC_667_COUNTS="
            + json.dumps(
                {
                    "universe": scan["full_universe_count"],
                    "material": scan["material_candidate_count"],
                    "hidden": scan["hidden_gem_count"],
                    "signals": scan["signal_counts"],
                },
                sort_keys=True,
            )
        )
    assert scan["full_universe_count"] == 667
    assert scan["scanned_count"] == 667
    assert scan["signal_counts"]["BREAKOUT"] == 100
    assert scan["signal_counts"]["POSITIVE_REGRESSION"] == 100
    assert scan["signal_counts"]["NEGATIVE_REGRESSION"] == 100
    assert scan["signal_counts"]["DEFCON_VALUE"] > 0
    assert elapsed_ms < 5000.0


def test_stagec_report_is_bounded_and_keeps_canonical_top_level_catalog():
    rows = []
    projections = []
    for index in range(30):
        element = 9300 + index
        rows.extend(_stagec_breakout_rows(element))
        projections.append(_stagec_projection(element, ownership=3.0, price=55))
    scan = build_universe_scan(
        projections={"players": projections},
        multiwindow_snapshot=build_multiwindow_form_snapshot(
            rows,
            season="2026/27",
        ),
    )
    challenges = build_external_challenge_layer([], scan=scan)
    surface = build_stagec_report_surface(
        scan=scan,
        external_challenges=challenges,
    )
    report = {
        "sections": [
            {
                "section_id": "S04",
                "label": "CHANGES",
                "state": "COMPLETE",
                "content": {
                    "changes": [
                        {
                            "type": "NO_NEW_MATERIAL_CHANGE",
                            "summary": "baseline",
                        }
                    ]
                },
            }
        ]
    }
    enriched = attach_stagec_to_deep_report(
        report,
        surface,
        enabled=True,
    )
    body = render_deep_text(enriched)
    for label in (
        "UNDERLYING TRAJECTORY",
        "POSITIVE REGRESSION WATCH",
        "NEGATIVE REGRESSION WATCH",
        "BREAKOUT / HIDDEN GEMS",
        "DEFCON OPPORTUNITIES",
        "ROLE / MINUTES CHANGES",
        "EXTERNAL CLAIM CHALLENGE",
    ):
        assert label in body
    assert len(enriched["sections"]) == 1
    assert enriched["sections"][0]["section_id"] == "S04"
    assert surface["rendered_row_count"] <= 35
    assert len(body) < 25000


def test_stagec_feature_off_report_is_exact_noop():
    report = {
        "sections": [
            {
                "section_id": "S04",
                "label": "CHANGES",
                "state": "COMPLETE",
                "content": {"changes": [{"summary": "baseline"}]},
            }
        ]
    }
    before = deepcopy(report)
    returned = attach_stagec_to_deep_report(
        report,
        {"contract": "V12_STAGEC_DEEP_SUBSECTIONS_V1"},
        enabled=False,
    )
    assert returned is report
    assert report == before
    assert render_deep_text(report) == render_deep_text(before)

def test_stagec_role_minutes_and_fixture_swing_classifications():
    gain_element = 9401
    gain_rows = []
    for gw in range(1, 7):
        recent = gw >= 4
        gain_rows.append(
            _mw_row(
                gw,
                player_id=gain_element,
                minutes=90 if recent else 45,
                starter=recent,
                goals=1 if gw in {3, 6} else 0,
                assists=0,
                xg=0.18 if recent else 0.09,
                npxg=0.18 if recent else 0.09,
                xa=0.07 if recent else 0.035,
                xgi=0.25 if recent else 0.125,
                shots=2 if recent else 1,
                shots_in_box=1,
                shots_on_target=1 if recent else 0,
                box_touches=5 if recent else 2.5,
                key_passes=1,
                chances_created=1,
            )
        )
    loss_element = 9402
    loss_rows = []
    for gw in range(1, 7):
        recent = gw >= 4
        loss_rows.append(
            _mw_row(
                gw,
                player_id=loss_element,
                minutes=45 if recent else 90,
                starter=not recent,
                goals=1 if gw in {3, 6} else 0,
                assists=0,
                xg=0.09 if recent else 0.18,
                npxg=0.09 if recent else 0.18,
                xa=0.035 if recent else 0.07,
                xgi=0.125 if recent else 0.25,
                shots=1 if recent else 2,
                shots_in_box=1,
                shots_on_target=0 if recent else 1,
                box_touches=2.5 if recent else 5,
                key_passes=1,
                chances_created=1,
            )
        )

    scan = _stagec_scan(
        [gain_rows, loss_rows],
        [
            _stagec_projection(
                gain_element,
                xmins=82,
                p_start=0.9,
                h1=7,
                h2=13,
                h3=18,
                h5=20,
            ),
            _stagec_projection(
                loss_element,
                xmins=50,
                p_start=0.55,
                h1=3,
                h2=6,
                h3=8,
                h5=18,
            ),
        ],
    )
    by_id = {row["element"]: row for row in scan["material_candidates"]}
    gain = by_id[gain_element]
    loss = by_id[loss_element]
    assert gain["signals"]["ROLE_GAIN"]["active"] is True
    assert gain["signals"]["MINUTES_GAIN"]["active"] is True
    assert gain["signals"]["FIXTURE_SWING"]["active"] is True
    assert gain["signals"]["FIXTURE_SWING"]["direction"] == "POSITIVE"
    assert loss["signals"]["ROLE_LOSS"]["active"] is True
    assert loss["signals"]["MINUTES_RISK"]["active"] is True
    assert loss["signals"]["FIXTURE_SWING"]["active"] is True
    assert loss["signals"]["FIXTURE_SWING"]["direction"] == "NEGATIVE"

def test_stagec_external_challenge_has_no_network_client_or_scraper():
    root = Path(__file__).resolve().parents[1]
    source = (
        root / "src" / "models" / "v12_external_challenge.py"
    ).read_text(encoding="utf-8").lower()
    forbidden = (
        "import requests",
        "import httpx",
        "urllib.request",
        "selenium",
        "playwright",
        "beautifulsoup",
        "cloudscraper",
    )
    assert not [token for token in forbidden if token in source]


def test_stagec_runner_feature_defaults_off(monkeypatch):
    from src.engines.v12_integrated_report_runner import (
        _stagec_scanner_enabled,
    )

    monkeypatch.delenv("V12_STAGEC_SCANNER_ENABLED", raising=False)
    assert _stagec_scanner_enabled() is False
    monkeypatch.setenv("V12_STAGEC_SCANNER_ENABLED", "1")
    assert _stagec_scanner_enabled() is True

