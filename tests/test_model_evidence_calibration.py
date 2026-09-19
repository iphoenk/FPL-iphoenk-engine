from __future__ import annotations

from copy import deepcopy

import pytest

from src.engines.v12_model_evidence import (
    ModelEvidenceError,
    aggregate_settled_ledgers,
    bind_deterministic_output,
    build_model_run_binding,
    decision_calibration_metrics,
    freeze_prediction,
    new_calibration_ledger,
    prediction_calibration_metrics,
    put_frozen_record,
    replace_with_settled_record,
    settle_frozen_record,
)


def _binding(**overrides):
    payload = dict(
        input_snapshot_id="v6-snapshot-gw5-001",
        factual_snapshot_timestamps={
            "official_fpl": "2026-09-19T11:30:00Z",
            "mini_league": "2026-09-19T11:31:00Z",
        },
        factual_artifact_fingerprints={
            "official_fpl": "a" * 64,
            "mini_league": "b" * 64,
        },
        deterministic_factual_inputs={
            "players": [
                {"element": 1, "price": 75, "minutes": 360},
                {"element": 2, "price": 80, "minutes": 270},
            ],
            "fixture": {"gw": 5, "home": 1, "away": 2},
        },
        model_version="v12-phase0-model-1",
        feature_version="v12-features-1",
        parameter_version="params-1",
        parameters={"alpha": 0.4, "beta": 0.6},
        calibration_version="cal-1",
        calibration_cutoff="2026-09-18T23:00:00Z",
        calibration_parameters={"prior_strength": 12},
        generated_at="2026-09-19T11:45:00Z",
        planning_gw=5,
        canonical_v12_revision="canonical-sha-001",
    )
    payload.update(overrides)
    return build_model_run_binding(**payload)


def _forecast_rows():
    return [
        {
            "element": 1,
            "position": "MID",
            "xpts": 6.0,
            "xmins": 80.0,
            "start_probability": 0.9,
            "dnp_probability": 0.05,
            "clean_sheet_probability": 0.35,
            "projection_confidence": "HIGH",
            "evidence_sample_size": 220,
        },
        {
            "element": 2,
            "position": "FWD",
            "xpts": 4.0,
            "xmins": 60.0,
            "start_probability": 0.7,
            "dnp_probability": 0.15,
            "clean_sheet_probability": None,
            "projection_confidence": "MEDIUM",
            "evidence_sample_size": 100,
        },
    ]


def _actual_rows():
    return [
        {"element": 1, "points": 8.0, "minutes": 90.0, "started": 1, "dnp": 0, "clean_sheet": 1},
        {"element": 2, "points": 2.0, "minutes": 25.0, "started": 0, "dnp": 0, "clean_sheet": 0},
    ]


def _frozen():
    return freeze_prediction(
        model_binding=_binding(),
        deadline_time="2026-09-19T12:00:00Z",
        forecast_generated_at="2026-09-19T11:50:00Z",
        frozen_at="2026-09-19T11:55:00Z",
        forecast_rows=_forecast_rows(),
    )


def test_same_snapshot_versions_ignore_wall_clock_in_deterministic_fingerprints():
    a = _binding(generated_at="2026-09-19T11:45:00Z")
    b = _binding(generated_at="2026-09-19T11:55:00Z")
    for key in ("input_fingerprint", "model_fingerprint", "parameter_fingerprint", "calibration_fingerprint", "run_fingerprint"):
        assert a[key] == b[key]
    assert a["generated_at"] != b["generated_at"]
    assert a["wall_clock_excluded_from_deterministic_fingerprint"] is True
    assert a["raw_factual_inputs_persisted"] is False


def test_changed_fact_model_parameters_and_calibration_change_separate_fingerprints():
    base = _binding()
    fact = _binding(deterministic_factual_inputs={"players": [{"element": 1, "price": 76}], "fixture": {"gw": 5}})
    model = _binding(model_version="v12-phase0-model-2")
    params = _binding(parameter_version="params-2", parameters={"alpha": 0.5})
    cal = _binding(calibration_version="cal-2", calibration_parameters={"prior_strength": 18})
    assert fact["input_fingerprint"] != base["input_fingerprint"]
    assert model["model_fingerprint"] != base["model_fingerprint"]
    assert params["parameter_fingerprint"] != base["parameter_fingerprint"]
    assert cal["calibration_fingerprint"] != base["calibration_fingerprint"]
    assert len({base["run_fingerprint"], fact["run_fingerprint"], model["run_fingerprint"], params["run_fingerprint"], cal["run_fingerprint"]}) == 5


def test_deterministic_output_binding_is_reproducible():
    binding = _binding()
    a = bind_deterministic_output(binding, {"xpts": [1.0, 2.0]})
    b = bind_deterministic_output(binding, {"xpts": [1.0, 2.0]})
    c = bind_deterministic_output(binding, {"xpts": [1.0, 2.1]})
    assert a["output_fingerprint"] == b["output_fingerprint"]
    assert a["output_fingerprint"] != c["output_fingerprint"]


def test_predeadline_freeze_is_immutable_and_postdeadline_forecast_rejected():
    record = _frozen()
    assert record["status"] == "FROZEN_AWAITING_SETTLEMENT"
    assert record["freeze_transition"] == "PREDEADLINE_FREEZE"
    with pytest.raises(ModelEvidenceError):
        freeze_prediction(
            model_binding=_binding(),
            deadline_time="2026-09-19T12:00:00Z",
            forecast_generated_at="2026-09-19T11:59:00Z",
            frozen_at="2026-09-19T12:01:00Z",
            forecast_rows=_forecast_rows(),
            existing_record=record,
        )
    with pytest.raises(ModelEvidenceError):
        freeze_prediction(
            model_binding=_binding(),
            deadline_time="2026-09-19T12:00:00Z",
            forecast_generated_at="2026-09-19T12:00:01Z",
            frozen_at="2026-09-19T12:01:00Z",
            forecast_rows=_forecast_rows(),
        )


def test_postdeadline_promotion_allowed_only_for_genuine_predeadline_payload():
    record = freeze_prediction(
        model_binding=_binding(),
        deadline_time="2026-09-19T12:00:00Z",
        forecast_generated_at="2026-09-19T11:59:00Z",
        frozen_at="2026-09-19T12:05:00Z",
        forecast_rows=_forecast_rows(),
    )
    assert record["freeze_transition"] == "PROMOTED_LAST_PREDEADLINE_SNAPSHOT"


def test_settlement_requires_finished_event_and_detects_hindsight_mutation():
    record = _frozen()
    with pytest.raises(ModelEvidenceError):
        settle_frozen_record(record, actual_rows=_actual_rows(), decision_outcome_evidence={}, event_finished=False, settled_at="2026-09-20T18:00:00Z")
    tampered = deepcopy(record)
    tampered["frozen_forecast"]["players"][0]["xpts"] = 99.0
    with pytest.raises(ModelEvidenceError):
        settle_frozen_record(tampered, actual_rows=_actual_rows(), decision_outcome_evidence={}, event_finished=True, settled_at="2026-09-20T18:00:00Z")


def test_prediction_metrics_cover_required_phase0_set_and_buckets():
    out = prediction_calibration_metrics(_forecast_rows(), _actual_rows())
    overall = out["overall"]
    assert overall["sample_size"] == 2
    assert overall["xpts_mae"] == 2.0
    assert overall["xpts_rmse"] == 2.0
    assert overall["xmins_mae"] == 22.5
    assert overall["starter_brier"] == 0.25
    assert overall["dnp_brier"] == 0.0125
    assert overall["clean_sheet_brier"] == pytest.approx((0.35 - 1.0) ** 2, abs=1e-4)
    assert overall["spearman_rank"] == 1.0
    assert out["by_confidence_bucket"]["HIGH"]["sample_size"] == 1
    assert out["by_confidence_bucket"]["MEDIUM"]["sample_size"] == 1
    assert out["by_sample_size_bucket"]["MEDIUM_SAMPLE"]["sample_size"] == 1
    assert out["by_sample_size_bucket"]["HIGH_SAMPLE"]["sample_size"] == 1


def test_decision_metrics_include_all_required_phase0_surfaces():
    out = decision_calibration_metrics({
        "chosen_transfer_net": 1.0,
        "best_transfer_or_hold_net": 3.5,
        "hold_realized_net": 4.0,
        "act_realized_net": 1.0,
        "chosen_action": "ACT",
        "selected_xi_points": 49.0,
        "best_legal_xi_points": 55.0,
        "realized_bench_order_autosub_points": 2.0,
        "best_legal_bench_autosub_points": 7.0,
        "chosen_captain_points": 4.0,
        "best_captain_candidate_points": 11.0,
        "vice_takeover_points": 10.0,
        "vice_counterfactual_points": 6.0,
        "cameo_points": 1.0,
        "blocked_legal_autosub_points": 8.0,
        "rental_player_points": 9.0,
        "hold_player_points": 4.0,
        "rental_exact_hit_cost": 4.0,
        "rental_exact_exit_cost": 0.0,
    })
    m = out["metrics"]
    assert m["transfer_counterfactual_regret"]["value"] == 2.5
    assert m["hold_vs_act_realized_regret"]["value"] == 3.0
    assert m["xi_regret"]["value"] == 6.0
    assert m["bench_order_regret"]["value"] == 5.0
    assert m["captain_regret"]["value"] == 7.0
    assert m["vice_captain_consequence"]["value"] == 4.0
    assert m["cameo_block_autosub_regret"]["value"] == 7.0
    assert m["one_gw_rental_realized_pnl"]["value"] == 1.0
    assert out["governance"]["legacy_fixed_change_penalty_forbidden"] is True


def test_one_gw_rental_pnl_requires_explicit_exact_cost_capture():
    out = decision_calibration_metrics({"rental_player_points": 9.0, "hold_player_points": 4.0})
    assert out["metrics"]["one_gw_rental_realized_pnl"]["status"] == "NO_GENUINE_PREDEADLINE_SAMPLE"


def test_settled_ledger_separates_prediction_from_decision_error():
    settled = settle_frozen_record(
        _frozen(),
        actual_rows=_actual_rows(),
        decision_outcome_evidence={"hold_realized_net": 3, "act_realized_net": 1, "chosen_action": "HOLD"},
        event_finished=True,
        settled_at="2026-09-20T18:00:00Z",
    )
    assert settled["status"] == "SETTLED"
    assert "prediction_calibration" in settled
    assert "decision_calibration" in settled
    assert settled["anti_hindsight"]["frozen_evidence_verified_before_settlement"] is True


def test_ledger_lifecycle_is_append_then_settle_not_rewrite():
    frozen = _frozen()
    ledger = put_frozen_record(new_calibration_ledger(), record_id="gw5-main", frozen_record=frozen)
    with pytest.raises(ModelEvidenceError):
        put_frozen_record(ledger, record_id="gw5-main", frozen_record=frozen)
    settled = settle_frozen_record(frozen, actual_rows=_actual_rows(), decision_outcome_evidence={}, event_finished=True, settled_at="2026-09-20T18:00:00Z")
    ledger2 = replace_with_settled_record(ledger, record_id="gw5-main", settled_record=settled)
    assert ledger2["records"]["gw5-main"]["status"] == "SETTLED"
    assert ledger2["governance"]["authority"] is False
    assert ledger2["governance"]["v6_factual_data_duplicated"] is False


def test_aggregate_uses_only_settled_samples_and_explicit_sample_size():
    frozen = _frozen()
    settled = settle_frozen_record(
        frozen,
        actual_rows=_actual_rows(),
        decision_outcome_evidence={"chosen_captain_points": 3, "best_captain_candidate_points": 8},
        event_finished=True,
        settled_at="2026-09-20T18:00:00Z",
    )
    summary = aggregate_settled_ledgers([frozen, settled])
    assert summary["settled_record_count"] == 1
    assert summary["prediction_sample_size"] == 2
    assert summary["calibration_confidence"] == "LOW"
    assert summary["decision_metrics"]["captain_regret"]["sample_size"] == 1
    assert summary["governance"]["automatic_methodology_weight_mutation"] is False


def test_migration_oracle_matches_legacy_calibration_on_no_tie_fixture():
    from src.models.calibration import brier as legacy_brier
    from src.models.calibration import mae as legacy_mae
    from src.models.calibration import spearman_rank as legacy_spearman

    out = prediction_calibration_metrics(_forecast_rows(), _actual_rows())["overall"]
    pred_points, actual_points = [6.0, 4.0], [8.0, 2.0]
    assert out["xpts_mae"] == round(legacy_mae(pred_points, actual_points), 4)
    assert out["starter_brier"] == round(legacy_brier([0.9, 0.7], [1, 0]), 4)
    assert out["spearman_rank"] == round(legacy_spearman(pred_points, actual_points), 4)


def test_phase0_module_has_no_v6_or_legacy_production_dependency():
    import inspect
    import src.engines.v12_model_evidence as module

    source = inspect.getsource(module)
    assert "src.runtime_v6" not in source
    assert "src.engines.prediction_evaluation" not in source
    assert "src.models.calibration" not in source
