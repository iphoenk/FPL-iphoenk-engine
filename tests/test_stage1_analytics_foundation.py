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
                    "tactical_role_component": {
                        "canonical_tactical_role_score": 50 + index
                    },
                    "horizons": {
                        "1": {"mean": 4 + index / 10},
                        "3": {"mean": 12 + index / 10},
                        "5": {"mean": 20 + index / 10},
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
