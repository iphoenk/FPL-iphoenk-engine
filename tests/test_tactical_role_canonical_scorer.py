from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from src.engines.canonical_decision_methodology import (
    CANONICAL_AUTHORITY,
    CANONICAL_WEIGHTS,
    compute_football_score,
)
from src.engines.v12_model_evidence import (
    build_model_run_binding,
    tactical_role_calibration_metrics,
)
from src.engines.v12_tactical_role import (
    CANONICAL_WEIGHT,
    TacticalRoleContractError,
    attach_tactical_role_scores,
    bounded_counterfactual_validation,
    compose_contextual_tactical_score,
    migration_comparison,
    score_player_fixture_context,
    score_tactical_role,
)


def evidence_row(
    feature_name,
    *,
    state="OBSERVED",
    value="POSITIVE_ROLE",
    direction="POSITIVE",
    confidence=0.9,
    materiality=1.0,
    double="TACTICAL_DISTINCT",
    source="TEST_SOURCE",
    reference="test:evidence",
):
    if state == "UNAVAILABLE":
        return {
            "feature_name": feature_name,
            "value": "UNKNOWN",
            "direction": "UNKNOWN",
            "evidence_state": "UNAVAILABLE",
            "source": None,
            "observed_at": None,
            "confidence": 0.0,
            "direct_or_inferred": "UNAVAILABLE",
            "materiality": 0.0,
            "double_count_classification": double,
            "supporting_evidence_reference": None,
        }
    return {
        "feature_name": feature_name,
        "value": value,
        "direction": direction,
        "evidence_state": state,
        "source": source,
        "observed_at": "2026-09-19T12:00:00Z",
        "confidence": confidence,
        "direct_or_inferred": "DIRECT" if state == "OBSERVED" else "INFERRED",
        "materiality": materiality,
        "double_count_classification": double,
        "supporting_evidence_reference": reference,
    }


def score(rows):
    return score_tactical_role(element=1, planning_gw=5, evidence=rows)


def feature(result, name):
    return next(
        row for row in result["feature_decomposition"]
        if row["feature_name"] == name
    )


def test_01_observed_evidence_has_greater_authority_than_inferred():
    result = score(
        [
            evidence_row(
                "attacking_freedom",
                state="INFERRED",
                value="LOW",
                direction="NEGATIVE",
            ),
            evidence_row(
                "attacking_freedom",
                state="OBSERVED",
                value="HIGH",
                direction="POSITIVE",
            ),
        ]
    )
    item = feature(result, "attacking_freedom")
    assert item["evidence_state"] == "OBSERVED"
    assert item["direction"] == "POSITIVE"
    assert item["superseded_lower_authority_count"] == 1


def test_02_unavailable_remains_unavailable():
    result = score(
        [evidence_row("actual_positional_deployment", state="UNAVAILABLE")]
    )
    item = feature(result, "actual_positional_deployment")
    assert item["evidence_state"] == "UNAVAILABLE"
    assert item["value"] == "UNKNOWN"
    assert item["canonical_tactical_contribution"] == 0.0


def test_03_missing_formation_is_not_invented():
    result = score([])
    assert result["system_fit"]["evidence_state"] == "UNAVAILABLE"
    assert result["system_fit"]["value"] == "UNKNOWN"


def test_04_missing_coach_information_is_not_invented():
    result = score([])
    assert feature(
        result, "coach_selection_consistency"
    )["evidence_state"] == "UNAVAILABLE"


def test_05_missing_penalty_and_set_piece_roles_are_not_fabricated():
    result = score([])
    assert result["penalty_role"]["state"] == "UNAVAILABLE"
    assert result["set_piece_role"]["state"] == "UNAVAILABLE"


def test_06_penalty_role_provenance_is_explicit():
    result = score_tactical_role(
        element=1,
        planning_gw=5,
        evidence=[evidence_row("penalty_hierarchy", value="PRIMARY")],
        penalty_role={
            "state": "OBSERVED",
            "source": "OFFICIAL_FPL_BOOTSTRAP",
            "penalty_primary": True,
        },
    )
    assert (
        feature(result, "penalty_hierarchy")["provenance"][0]["source"]
        == "TEST_SOURCE"
    )
    assert result["penalty_role"]["source"] == "OFFICIAL_FPL_BOOTSTRAP"


def test_07_set_piece_role_provenance_is_explicit():
    result = score_tactical_role(
        element=1,
        planning_gw=5,
        evidence=[evidence_row("set_piece_hierarchy", value="PRIMARY")],
        set_piece_role={
            "state": "OBSERVED",
            "source": "OFFICIAL_FPL_BOOTSTRAP",
            "corners": "PRIMARY",
        },
    )
    assert result["set_piece_role"]["source"] == "OFFICIAL_FPL_BOOTSTRAP"


@pytest.mark.parametrize(
    "name",
    [
        "current_xg",
        "current_xa",
        "current_shots",
        "current_chances_created",
    ],
)
def test_08_09_current_underlying_cannot_silently_enter_tactical(name):
    with pytest.raises(TacticalRoleContractError):
        score(
            [
                {
                    "feature_name": name,
                    "evidence_state": "OBSERVED",
                    "source": "TEST",
                    "confidence": 1.0,
                    "direct_or_inferred": "DIRECT",
                    "materiality": 1.0,
                    "double_count_classification": "TACTICAL_DISTINCT",
                    "supporting_evidence_reference": "test",
                    "value": "HIGH",
                    "direction": "POSITIVE",
                }
            ]
        )


def test_10_generic_fixture_strength_cannot_silently_double_count():
    with pytest.raises(TacticalRoleContractError):
        score(
            [
                {
                    "feature_name": "generic_fixture_strength",
                    "evidence_state": "OBSERVED",
                    "source": "TEST",
                    "confidence": 1.0,
                    "direct_or_inferred": "DIRECT",
                    "materiality": 1.0,
                    "double_count_classification": "TACTICAL_DISTINCT",
                    "supporting_evidence_reference": "test",
                    "value": "EASY",
                    "direction": "POSITIVE",
                }
            ]
        )


def test_11_tactical_channel_benefit_requires_role_channel_compatibility():
    result = score(
        [
            evidence_row(
                "opponent_wide_vulnerability",
                value="WEAKNESS_OBSERVED",
                double="TACTICAL_INTERACTION_ROLE_MATCHED",
            )
        ]
    )
    item = feature(result, "opponent_wide_vulnerability")
    assert (
        item["double_count_classification"]
        == "CONTEXT_ONLY_UNMATCHED_ROLE_CHANNEL"
    )
    assert item["canonical_tactical_contribution"] == 0.0


def test_12_wide_weakness_does_not_boost_central_only_player():
    result = score(
        [
            evidence_row(
                "central_wide_half_space_deployment",
                value="CENTRAL",
                direction="NEUTRAL",
            ),
            evidence_row(
                "opponent_wide_vulnerability",
                value="WEAKNESS_OBSERVED",
                double="TACTICAL_INTERACTION_ROLE_MATCHED",
            ),
        ]
    )
    item = feature(result, "opponent_wide_vulnerability")
    assert item["interaction_guard_downgraded"] is True
    assert item["canonical_tactical_contribution"] == 0.0


def test_13_partial_evidence_reduces_confidence():
    partial = score(
        [evidence_row("set_piece_hierarchy", value="PRIMARY")]
    )
    fuller = score(
        [
            evidence_row("set_piece_hierarchy", value="PRIMARY"),
            evidence_row("penalty_hierarchy", value="PRIMARY"),
            evidence_row("attacking_freedom", value="HIGH"),
        ]
    )
    assert partial["confidence"] < fuller["confidence"]
    assert (
        partial["tactical_role_uncertainty"]
        > fuller["tactical_role_uncertainty"]
    )


def test_14_identical_evidence_gives_deterministic_score():
    rows = [evidence_row("set_piece_hierarchy", value="PRIMARY")]
    assert score(rows) == score(deepcopy(rows))


def test_15_conflicting_evidence_is_deterministic_and_transparent():
    result = score(
        [
            evidence_row(
                "attacking_freedom",
                value="HIGH",
                direction="POSITIVE",
                reference="a",
            ),
            evidence_row(
                "attacking_freedom",
                value="LOW",
                direction="NEGATIVE",
                reference="b",
            ),
        ]
    )
    item = feature(result, "attacking_freedom")
    assert item["conflict"] is True
    assert item["direction"] == "MIXED"
    assert (
        item["double_count_classification"]
        == "MIXED_OR_CONFLICTED_EXCLUDED"
    )
    assert result["role_state"] == "CONFLICTED"


def test_16_tactical_score_remains_bounded():
    result = score(
        [
            evidence_row("attacking_freedom", value="HIGH"),
            evidence_row("set_piece_hierarchy", value="PRIMARY"),
            evidence_row("penalty_hierarchy", value="PRIMARY"),
            evidence_row("system_formation_fit", value="GOOD_FIT"),
        ]
    )
    assert 0.0 <= result["tactical_role_score"] <= 100.0


def test_17_exact_tactical_weight_is_preserved():
    result = score(
        [evidence_row("set_piece_hierarchy", value="PRIMARY")]
    )
    assert CANONICAL_WEIGHT == 0.25
    assert result["canonical_component"]["weight"] == 0.25
    assert result["canonical_component"]["dynamic_weight_shift"] is False


def test_18_exact_overall_20_25_30_25_is_preserved():
    tactical = score(
        [evidence_row("set_piece_hierarchy", value="PRIMARY")]
    )
    football = compute_football_score(
        {
            "PROVEN_HISTORICAL": 60.0,
            "TACTICAL_ROLE": tactical["tactical_role_score"],
            "CURRENT_UNDERLYING": 70.0,
            "FIXTURE_SECURITY": 55.0,
        },
        weights=CANONICAL_WEIGHTS,
        authority=CANONICAL_AUTHORITY,
    )
    assert football["weights"] == {
        "PROVEN_HISTORICAL": 0.20,
        "TACTICAL_ROLE": 0.25,
        "CURRENT_UNDERLYING": 0.30,
        "FIXTURE_SECURITY": 0.25,
    }


def sample_projection():
    return {
        "players": [
            {
                "element": 1,
                "xmins": {
                    "probability_state": {
                        "unconditional": {
                            "p_start": 0.8,
                            "p_dnp": 0.1,
                        }
                    },
                    "mean": 70.0,
                },
                "posterior_rates": {
                    "goal": {"posterior_rate90": 0.4},
                    "assist": {"posterior_rate90": 0.2},
                },
                "xpts_by_gw": [
                    {"gw": 5, "mean": 6.2, "points_variance": 4.0}
                ],
                "set_piece_role": {
                    "source": "OFFICIAL_FPL_BOOTSTRAP",
                    "corners_and_indirect_freekicks_order": 1,
                    "direct_freekicks_order": 2,
                },
                "penalty_role": {
                    "source": "OFFICIAL_FPL_BOOTSTRAP",
                    "order": 1,
                },
                "tactical_matchup": {
                    "opponent_vulnerabilities": [
                        "set_piece_activity",
                        "wide_delivery",
                    ],
                    "opponent_observed_style_proxies": [],
                    "evidence_confidence": "HIGH",
                    "evidence_timestamp": "2026-09-19T12:00:00Z",
                    "provenance": {
                        "opponent_profile": "OBSERVED_TACTICAL_CONTEXT"
                    },
                },
            }
        ]
    }


def test_19_p1_3_event_probabilities_are_unchanged():
    projections = sample_projection()
    before_rates = deepcopy(
        projections["players"][0]["posterior_rates"]
    )
    before_xpts = deepcopy(projections["players"][0]["xpts_by_gw"])
    attach_tactical_role_scores(projections, 5)
    assert projections["players"][0]["posterior_rates"] == before_rates
    assert projections["players"][0]["xpts_by_gw"] == before_xpts


def test_20_p1_1_minutes_probabilities_are_unchanged():
    projections = sample_projection()
    before = deepcopy(projections["players"][0]["xmins"])
    attach_tactical_role_scores(projections, 5)
    assert projections["players"][0]["xmins"] == before


def test_21_phase0_model_evidence_binding_works():
    binding = build_model_run_binding(
        input_snapshot_id="snapshot-1",
        factual_snapshot_timestamps={
            "official": "2026-09-19T12:00:00Z"
        },
        factual_artifact_fingerprints={"official": "a" * 64},
        deterministic_factual_inputs={"ids": [1]},
        model_version="v12-tactical-role-canonical-v1",
        feature_version="tactical-role-features-v1",
        parameter_version="p1.6-tactical-role-v1",
        parameters={"weight": 0.25},
        calibration_version="none",
        calibration_cutoff="2026-09-18T00:00:00Z",
        calibration_parameters={},
        generated_at="2026-09-19T12:00:00Z",
        planning_gw=5,
        canonical_v12_revision="p1.6",
    )
    binding.update({"authority": False, "evidence_only": True})
    result = score_tactical_role(
        element=1,
        planning_gw=5,
        evidence=[evidence_row("set_piece_hierarchy", value="PRIMARY")],
        model_evidence_binding=binding,
    )
    assert result["model_evidence"]["status"] == "PASS"
    assert len(result["model_evidence_binding"]["run_fingerprint"]) == 64
    assert len(result["model_evidence_binding"]["output_fingerprint"]) == 64
    assert result["model_evidence_binding"]["authority"] is False


def test_22_no_raw_v6_duplication():
    result = score([])
    assert result["provenance"]["raw_v6_payload_persisted"] is False
    assert "raw_v6_payload" not in result


def test_23_24_no_v6_or_runtime_v3_production_dependency():
    text = Path("src/engines/v12_tactical_role.py").read_text(
        encoding="utf-8"
    ).lower()
    for forbidden in (
        "from src.runtime_v6",
        "import src.runtime_v6",
        "from src.runtime_v3",
        "import src.runtime_v3",
    ):
        assert forbidden not in text


def test_25_26_27_28_future_stages_are_not_imported():
    text = Path("src/engines/v12_tactical_role.py").read_text(
        encoding="utf-8"
    ).lower()
    for forbidden in (
        "from src.engines.package_optimizer",
        "import src.engines.package_optimizer",
        "from src.engines.monte_carlo",
        "import src.engines.monte_carlo",
        "from src.engines.mini_league",
        "import src.engines.mini_league",
        "from src.engines.lineup_optimizer",
        "import src.engines.lineup_optimizer",
    ):
        assert forbidden not in text


def test_29_migration_comparison_has_zero_unexpected_regression():
    native = score(
        [evidence_row("set_piece_hierarchy", value="PRIMARY")]
    )
    comparison = migration_comparison(native, {"status": "READY"})
    assert comparison["unexpected_regression_count"] == 0
    assert (
        "INTENTIONAL_CANONICAL_MAPPING"
        in comparison["categories"]
    )


def test_30_calibration_hooks_are_diagnostic_only():
    output = tactical_role_calibration_metrics(
        [
            {
                "settled": True,
                "tactical_role_score": 60.0,
                "realized_tactical_score": 70.0,
                "confidence": 0.4,
                "direction_correct": True,
                "decision_correct": True,
                "feature_decomposition": [
                    {
                        "feature_name": "set_piece_hierarchy",
                        "canonical_tactical_contribution": 0.8,
                    }
                ],
            }
        ]
    )
    assert output["settled_sample_size"] == 1
    assert output["calibration_confidence"] == "LOW"
    assert output["governance"]["automatic_retuning"] is False
    assert output["governance"]["canonical_weight_mutation"] is False



def contextual_player():
    return {
        "element": 901,
        "team_id": 1,
        "position": "MID",
        "element_type": 3,
        "current_season": {"starts": 4, "minutes": 360},
        "xmins": {
            "start_probability": 0.90,
            "expected_minutes": 78.0,
            "starter_minutes_if_start": 82.0,
        },
        "posterior_rates": {
            "goal": {
                "posterior_rate90": 0.40,
                "prior": 0.20,
            },
            "assist": {
                "posterior_rate90": 0.30,
                "prior": 0.20,
            },
            "bonus": {
                "posterior_rate90": 0.35,
                "prior": 0.28,
            },
            "defcon": {
                "eligible": True,
                "posterior_count_rate90": 8.0,
                "threshold": 12,
            },
        },
        "tactical_role": {
            "evidence_minutes": 360,
            "metrics": {
                "xg_per90": 0.40,
                "xa_per90": 0.30,
                "shots_per90": 2.8,
                "touches_opposition_box_per90": 5.5,
                "chances_created_per90": 2.5,
            },
        },
        "tactical_matchup": {
            "opponent_team_id": 2,
            "tactical_edge": ["wide_delivery", "chance_creation"],
            "tactical_risk": ["box_pressure"],
            "tactical_matchup_label": "MIXED",
            "evidence_confidence": "HIGH",
        },
    }


def contextual_fixture(home=True):
    return {
        "event": 5,
        "fixture": "gw5:1:2",
        "home": home,
        "opponent": 2,
    }


def contextual_strength(opponent_scale=1.0):
    return {
        "baseline": {
            "home_goals": 1.55,
            "away_goals": 1.25,
        },
        "teams": [
            {
                "team_id": 1,
                "matches_played": 4,
                "attack_home_index": 1.20,
                "attack_away_index": 1.00,
                "defence_home_index": 1.10,
                "defence_away_index": 1.00,
            },
            {
                "team_id": 2,
                "matches_played": 4,
                "attack_home_index": 1.25 * opponent_scale,
                "attack_away_index": 1.15 * opponent_scale,
                "defence_home_index": 1.30 * opponent_scale,
                "defence_away_index": 1.10 * opponent_scale,
            },
        ],
    }


def contextual_roles():
    return (
        {
            "state": "OBSERVED",
            "source": "OFFICIAL_FPL_BOOTSTRAP",
            "corners": "PRIMARY",
            "direct_free_kick": "SECONDARY",
            "indirect_free_kick": "PRIMARY",
        },
        {
            "state": "OBSERVED",
            "source": "OFFICIAL_FPL_BOOTSTRAP",
            "hierarchy": "PRIMARY",
            "penalty_primary": True,
        },
    )


def compose_case(**overrides):
    payload = {
        "evidence_role_score": 75.0,
        "home_attack_context": 0.65,
        "attacking_involvement_score": 0.75,
        "role_security_score": 0.80,
        "scoring_channel_diversity": 0.65,
        "tactical_role_fit": 0.70,
        "fixture_suppression_raw": 0.35,
    }
    payload.update(overrides)
    return compose_contextual_tactical_score(**payload)


def test_31_strong_role_difficult_fixture_is_not_automatic_rejection():
    strong = compose_case(
        evidence_role_score=80.0,
        home_attack_context=0.80,
        attacking_involvement_score=0.90,
        role_security_score=0.90,
        scoring_channel_diversity=0.80,
        tactical_role_fit=0.80,
        fixture_suppression_raw=0.50,
    )
    weak = compose_case(
        evidence_role_score=35.0,
        home_attack_context=0.50,
        attacking_involvement_score=0.30,
        role_security_score=0.30,
        scoring_channel_diversity=0.20,
        tactical_role_fit=0.30,
        fixture_suppression_raw=0.50,
    )
    assert strong["canonical_tactical_role_score"] > weak["canonical_tactical_role_score"]
    assert strong["fixture_suppression_effective"] > 0.0
    assert strong["canonical_tactical_role_score"] > 0.0


def test_32_weak_role_easy_fixture_is_not_automatic_recommendation():
    weak_easy = compose_case(
        evidence_role_score=35.0,
        home_attack_context=0.50,
        attacking_involvement_score=0.30,
        role_security_score=0.30,
        scoring_channel_diversity=0.20,
        tactical_role_fit=0.30,
        fixture_suppression_raw=0.0,
    )
    strong_easy = compose_case(
        evidence_role_score=80.0,
        home_attack_context=0.50,
        attacking_involvement_score=0.90,
        role_security_score=0.90,
        scoring_channel_diversity=0.80,
        tactical_role_fit=0.80,
        fixture_suppression_raw=0.0,
    )
    assert weak_easy["canonical_tactical_role_score"] < strong_easy["canonical_tactical_role_score"]


def test_33_meaningful_channel_diversity_can_improve_score():
    single = compose_case(scoring_channel_diversity=0.10)
    multi = compose_case(scoring_channel_diversity=0.80)
    assert multi["canonical_tactical_role_score"] > single["canonical_tactical_role_score"]


def test_34_fixture_suppression_is_bounded():
    result = compose_case(fixture_suppression_raw=5.0)
    assert result["fixture_suppression_raw"] == 1.0
    assert 0.0 <= result["fixture_suppression_effective"] <= 1.0


def test_35_resilience_reduces_but_never_erases_suppression():
    low = compose_case(
        home_attack_context=0.10,
        attacking_involvement_score=0.10,
        role_security_score=0.10,
        scoring_channel_diversity=0.10,
        tactical_role_fit=0.10,
        fixture_suppression_raw=0.80,
    )
    high = compose_case(
        home_attack_context=1.0,
        attacking_involvement_score=1.0,
        role_security_score=1.0,
        scoring_channel_diversity=1.0,
        tactical_role_fit=1.0,
        fixture_suppression_raw=0.80,
    )
    assert high["fixture_suppression_effective"] < low["fixture_suppression_effective"]
    assert high["fixture_suppression_effective"] > 0.0
    assert high["fixture_suppression_effective"] <= high["fixture_suppression_raw"]


def test_36_home_context_is_applied_once_and_separated_from_raw_suppression():
    set_piece, penalty = contextual_roles()
    output = score_player_fixture_context(
        player=contextual_player(),
        fixture=contextual_fixture(home=True),
        evidence_role_score=70.0,
        team_strength=contextual_strength(),
        set_piece_role=set_piece,
        penalty_role=penalty,
    )
    home = output["feature_evidence"]["home_attack_context"]
    suppression = output["feature_evidence"]["fixture_suppression_raw"]
    assert home["application_count"] == 1
    assert home["generic_opponent_strength_consumed"] is False
    assert suppression["venue_specific_delta_excluded"] is True
    assert output["double_count_diagnostics"]["home_context_application_count"] == 1


def test_37_transfer_cost_is_not_part_of_intrinsic_tactical_score():
    set_piece, penalty = contextual_roles()
    base_player = contextual_player()
    expensive = deepcopy(base_player)
    expensive.update(
        {
            "now_cost": 150,
            "hit_points": 4,
            "bank": 0,
            "free_transfers": 0,
            "package_constraint": "DIFFERENT",
        }
    )
    cheap = deepcopy(base_player)
    cheap.update(
        {
            "now_cost": 40,
            "hit_points": 0,
            "bank": 100,
            "free_transfers": 5,
            "package_constraint": "OTHER",
        }
    )
    kwargs = {
        "fixture": contextual_fixture(),
        "evidence_role_score": 70.0,
        "team_strength": contextual_strength(),
        "set_piece_role": set_piece,
        "penalty_role": penalty,
    }
    left = score_player_fixture_context(player=expensive, **kwargs)
    right = score_player_fixture_context(player=cheap, **kwargs)
    assert left["canonical_tactical_role_score"] == right["canonical_tactical_role_score"]
    assert left["double_count_diagnostics"]["transfer_action_cost_present"] is False


def test_38_increasing_role_security_cannot_reduce_score_all_else_equal():
    low = compose_case(role_security_score=0.20)
    high = compose_case(role_security_score=0.90)
    assert high["canonical_tactical_role_score"] >= low["canonical_tactical_role_score"]


def test_39_increasing_attacking_involvement_cannot_reduce_score_all_else_equal():
    low = compose_case(attacking_involvement_score=0.20)
    high = compose_case(attacking_involvement_score=0.90)
    assert high["canonical_tactical_role_score"] >= low["canonical_tactical_role_score"]


def test_40_worse_opponent_cannot_improve_score_all_else_equal():
    easier = compose_case(fixture_suppression_raw=0.10)
    harder = compose_case(fixture_suppression_raw=0.70)
    assert harder["canonical_tactical_role_score"] <= easier["canonical_tactical_role_score"]


def test_41_same_snapshot_and_model_inputs_are_exactly_deterministic():
    set_piece, penalty = contextual_roles()
    kwargs = {
        "player": contextual_player(),
        "fixture": contextual_fixture(),
        "evidence_role_score": 70.0,
        "team_strength": contextual_strength(),
        "set_piece_role": set_piece,
        "penalty_role": penalty,
    }
    assert score_player_fixture_context(**deepcopy(kwargs)) == score_player_fixture_context(**deepcopy(kwargs))


def test_42_missing_optional_tactical_evidence_is_explicit_not_silent_zero():
    player = contextual_player()
    player.pop("tactical_matchup")
    set_piece, penalty = contextual_roles()
    output = score_player_fixture_context(
        player=player,
        fixture=contextual_fixture(),
        evidence_role_score=70.0,
        team_strength=contextual_strength(),
        set_piece_role=set_piece,
        penalty_role=penalty,
    )
    assert output["tactical_role_fit"] is None
    assert output["feature_evidence"]["tactical_role_fit"]["state"] == "UNAVAILABLE"
    assert output["missing_data"]["missing_is_zero"] is False
    assert output["canonical_tactical_role_score"] is not None


def test_43_no_legacy_v3_v4_v5_fallback_in_p1_6_owner():
    text = Path("src/engines/v12_tactical_role.py").read_text(encoding="utf-8").lower()
    for forbidden in (
        "from src.runtime_v3",
        "from src.runtime_v4",
        "from src.runtime_v5",
        "import src.runtime_v3",
        "import src.runtime_v4",
        "import src.runtime_v5",
    ):
        assert forbidden not in text


def test_44_no_v6_mutation_or_import_in_p1_6_owner():
    text = Path("src/engines/v12_tactical_role.py").read_text(encoding="utf-8").lower()
    assert "from src.runtime_v6" not in text
    assert "import src.runtime_v6" not in text
    assert "atomic_json(" not in text


def test_45_no_package_optimizer_invocation_from_p1_6_owner():
    text = Path("src/engines/v12_tactical_role.py").read_text(encoding="utf-8").lower()
    assert "from src.engines.package_optimizer" not in text
    assert "import src.engines.package_optimizer" not in text
    assert "package_optimizer(" not in text


def test_46_no_monte_carlo_invocation_from_p1_6_owner():
    text = Path("src/engines/v12_tactical_role.py").read_text(encoding="utf-8").lower()
    assert "from src.engines.monte_carlo" not in text
    assert "import src.engines.monte_carlo" not in text
    assert "monte_carlo(" not in text


def test_47_no_player_or_club_specific_runtime_patch():
    text = Path("src/engines/v12_tactical_role.py").read_text(encoding="utf-8").casefold()
    for forbidden in ("pascal", "groß", "gross", "brighton", "arsenal"):
        assert forbidden not in text


def test_48_counterfactual_matrix_covers_required_representative_cases():
    result = bounded_counterfactual_validation()
    assert result["historical_outcomes_used"] is False
    assert result["named_player_examples_used"] is False
    assert set(result["scenarios"]) == {
        "difficult_fixture_strong_role",
        "difficult_fixture_weak_role",
        "easy_fixture_strong_role",
        "easy_fixture_weak_role",
        "home_strong_role",
        "away_strong_role",
        "multi_channel_role",
        "single_channel_role",
    }
    assert all(result["hypotheses"].values())
    assert (
        result["historical_support_status"]
        == "UNPROVEN_UNTIL_SETTLED_PREDEADLINE_P1_5_SAMPLES_EXIST"
    )


def test_49_contextual_feature_contract_exposes_required_fields():
    set_piece, penalty = contextual_roles()
    output = score_player_fixture_context(
        player=contextual_player(),
        fixture=contextual_fixture(),
        evidence_role_score=70.0,
        team_strength=contextual_strength(),
        set_piece_role=set_piece,
        penalty_role=penalty,
    )
    required = {
        "home_attack_context",
        "attacking_involvement_score",
        "role_security_score",
        "scoring_channel_vector",
        "scoring_channel_diversity",
        "tactical_role_fit",
        "fixture_suppression_raw",
        "role_resilience",
        "fixture_suppression_effective",
        "canonical_tactical_role_score",
    }
    assert required <= set(output)
    assert 0.0 <= output["canonical_tactical_role_score"] <= 100.0
    assert output["model_version"] == "v12-tactical-role-canonical-v2"
    assert output["feature_version"] == "tactical-role-contextual-features-v2"
    assert output["parameter_version"] == "p1.6-contextual-role-v2"


def test_50_contextual_calibration_hook_remains_low_without_settled_history():
    output = tactical_role_calibration_metrics([])
    assert output["settled_sample_size"] == 0
    assert output["calibration_confidence"] == "LOW"
    assert output["parameter_binding"]["parameter_set_id"] == "P1_6_CONTEXTUAL_BOUNDED_STRUCTURAL_V1"
    assert output["governance"]["automatic_retuning"] is False
    assert output["governance"]["named_player_parameter_tuning_forbidden"] is True
