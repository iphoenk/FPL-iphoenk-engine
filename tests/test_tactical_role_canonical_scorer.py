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
    migration_comparison,
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
