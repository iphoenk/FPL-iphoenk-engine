from __future__ import annotations

from pathlib import Path

import pytest

from src.engines.v12_model_evidence import (
    ModelEvidenceError,
    build_model_run_binding,
    freeze_prediction,
    new_durable_state_evidence_surface,
    persist_frozen_to_state,
    settle_durable_state_record,
    validate_operational_model_evidence,
)


ROOT = Path(__file__).resolve().parents[1]


def _binding():
    built = build_model_run_binding(
        input_snapshot_id="v6:g5:slot-1900",
        factual_snapshot_timestamps={"official_fpl": "2026-09-19T11:30:00Z"},
        factual_artifact_fingerprints={"official_fpl": "a" * 64},
        deterministic_factual_inputs={"official_ref": "runtime-data-v6/official_fpl", "planning_gw": 5},
        model_version="v12-phase0-model-1",
        feature_version="v12-features-1",
        parameter_version="params-1",
        parameters={"alpha": 0.5},
        calibration_version="cal-1",
        calibration_cutoff="2026-09-19T10:00:00Z",
        calibration_parameters={"prior_strength": 12},
        generated_at="2026-09-19T11:45:00Z",
        planning_gw=5,
        canonical_v12_revision="c" * 64,
    )
    return {**built, "authority": False, "evidence_only": True}


def _forecast():
    return [{
        "element": 1,
        "position": "MID",
        "xpts": 5.5,
        "xmins": 82.0,
        "start_probability": 0.91,
        "dnp_probability": 0.03,
        "clean_sheet_probability": 0.35,
        "projection_confidence": "HIGH",
        "evidence_sample_size": 200,
    }]


def _frozen():
    return freeze_prediction(
        model_binding=_binding(),
        deadline_time="2026-09-19T12:00:00Z",
        forecast_generated_at="2026-09-19T11:50:00Z",
        frozen_at="2026-09-19T11:55:00Z",
        forecast_rows=_forecast(),
        decision_snapshot={"captured_at": "2026-09-19T11:54:00Z", "action": "HOLD"},
    )


def test_serious_decision_cannot_claim_reproducibility_without_binding():
    degraded = validate_operational_model_evidence(None, serious_decision=True)
    assert degraded["status"] == "DEGRADED"
    assert degraded["reproducible"] is False
    assert degraded["report_can_continue"] is True
    with pytest.raises(ModelEvidenceError):
        validate_operational_model_evidence(None, serious_decision=True, reproducibility_claimed=True)


def test_model_binding_is_non_authoritative_and_raw_v6_payload_is_forbidden():
    good = validate_operational_model_evidence(_binding(), reproducibility_claimed=True)
    assert good["status"] == "PASS"
    assert good["authority"] is False
    assert good["evidence_only"] is True
    bad = {**_binding(), "raw_v6_payload": {"players": [1, 2, 3]}}
    with pytest.raises(ModelEvidenceError):
        validate_operational_model_evidence(bad)


def test_uncomputed_fingerprint_makes_evidence_degraded_not_fake_pass():
    binding = _binding()
    binding["run_fingerprint"] = None
    result = validate_operational_model_evidence(binding)
    assert result["status"] == "DEGRADED"
    assert "run_fingerprint" in result["uncomputed_fingerprints"]
    assert result["report_can_continue"] is True


def test_repository_python_execution_claim_requires_occurrence_bound_proof():
    with pytest.raises(ModelEvidenceError):
        validate_operational_model_evidence(
            _binding(),
            repository_python_executed=True,
            repository_python_execution_proof={"occurrence_bound": False},
        )
    result = validate_operational_model_evidence(
        _binding(),
        repository_python_executed=True,
        repository_python_execution_proof={
            "occurrence_bound": True,
            "module": "src/engines/v12_model_evidence.py",
            "execution_id": "occurrence-20260919T1830+07",
        },
    )
    assert result["repository_python_executed"] is True


def test_predeadline_freeze_is_required_before_durable_settlement():
    state = new_durable_state_evidence_surface()
    with pytest.raises(ModelEvidenceError):
        settle_durable_state_record(
            state,
            record_id="missing",
            actual_rows=[],
            decision_outcome_evidence={},
            event_finished=True,
            settled_at="2026-09-20T18:00:00Z",
        )


def test_settlement_cannot_manufacture_or_replace_old_forecast():
    state = persist_frozen_to_state(new_durable_state_evidence_surface(), record_id="gw5:deadline", frozen_record=_frozen())
    with pytest.raises(ModelEvidenceError):
        persist_frozen_to_state(state, record_id="gw5:deadline", frozen_record=_frozen())


def test_actual_outcome_cannot_alter_frozen_fingerprint():
    frozen = _frozen()
    state = persist_frozen_to_state(new_durable_state_evidence_surface(), record_id="gw5:deadline", frozen_record=frozen)
    fingerprint_before = state["records"]["gw5:deadline"]["frozen_evidence_fingerprint"]
    settled = settle_durable_state_record(
        state,
        record_id="gw5:deadline",
        actual_rows=[{"element": 1, "points": 2.0, "minutes": 20.0, "started": 0, "dnp": 0, "clean_sheet": 0}],
        decision_outcome_evidence={"hold_realized_net": 2, "act_realized_net": 0, "chosen_action": "HOLD"},
        event_finished=True,
        settled_at="2026-09-20T18:00:00Z",
    )
    assert settled["records"]["gw5:deadline"]["frozen_evidence_fingerprint"] == fingerprint_before
    assert settled["records"]["gw5:deadline"]["actual_outcome_fingerprint"]


def test_post_all_settlement_requires_finished_event():
    state = persist_frozen_to_state(new_durable_state_evidence_surface(), record_id="gw5:deadline", frozen_record=_frozen())
    with pytest.raises(ModelEvidenceError):
        settle_durable_state_record(
            state,
            record_id="gw5:deadline",
            actual_rows=[],
            decision_outcome_evidence={},
            event_finished=False,
            settled_at="2026-09-20T18:00:00Z",
        )


def test_evidence_lifecycle_frozen_to_settled_and_calibration_is_diagnostic():
    state = persist_frozen_to_state(new_durable_state_evidence_surface(), record_id="gw5:deadline", frozen_record=_frozen())
    assert state["records"]["gw5:deadline"]["status"] == "FROZEN_AWAITING_SETTLEMENT"
    settled = settle_durable_state_record(
        state,
        record_id="gw5:deadline",
        actual_rows=[{"element": 1, "points": 7.0, "minutes": 90.0, "started": 1, "dnp": 0, "clean_sheet": 1}],
        decision_outcome_evidence={"chosen_captain_points": 7, "best_captain_candidate_points": 9},
        event_finished=True,
        settled_at="2026-09-20T18:00:00Z",
    )
    record = settled["records"]["gw5:deadline"]
    assert record["status"] == "SETTLED"
    assert record["prediction_calibration"]["overall"]["xpts_mae"] == 1.5
    assert record["decision_calibration"]["metrics"]["captain_regret"]["value"] == 2.0
    assert settled["automatic_methodology_weight_mutation"] is False


def test_canonical_requires_fail_operational_model_evidence_and_no_fake_python_claim():
    canonical = (ROOT / "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt").read_text(encoding="utf-8")
    assert "9D. MODEL EVIDENCE EXECUTION BINDING" in canonical
    assert "MODEL_EVIDENCE=DEGRADED/UNPROVEN" in canonical
    assert "MUST NOT suppress a due visible report" in canonical
    assert "Never infer repository_python_executed=true from code existence, CI success or imports." in canonical
    assert "never automatically changes the canonical 20/25/30/25 weights" in canonical


def test_durable_state_surface_is_existing_non_authoritative_json_only():
    import json
    state = json.loads((ROOT / "control/fpl_master_v12/FPL_MASTER_STATE_V12.json").read_text(encoding="utf-8"))
    evidence = state["model_evidence"]
    assert state["authority"] is False
    assert evidence["authority"] is False
    assert evidence["evidence_only"] is True
    assert evidence["raw_v6_payload_persisted"] is False
    assert evidence["records"] == {}
    assert evidence["automatic_methodology_weight_mutation"] is False


def test_phase0c_adds_no_v6_or_legacy_production_dependency():
    source = (ROOT / "src/engines/v12_model_evidence.py").read_text(encoding="utf-8")
    assert "src.runtime_v6" not in source
    assert "src.runtime_v3" not in source
    assert "src.models.xmins_v3" not in source
    assert "src.engines.prediction_evaluation" not in source


def test_state_revision_metadata_and_historical_migration_provenance_are_explicit():
    import json

    state = json.loads((ROOT / "control/fpl_master_v12/FPL_MASTER_STATE_V12.json").read_text(encoding="utf-8"))
    assert state["updated_at"] == "2026-09-20T17:19:58+07:00"
    assert state["updated_at_basis"] == "STATE_SEMANTIC_REVISION_COMMIT_ec2d5880e70eafd0bf1de2c28be768abd55ec740_AT_2026-09-20T10:19:58Z"
    assert state["authority"] is False
    assert state["non_authoritative_state_file"] is True
    assert state["latest_explicit_user_state_wins"] is True
    assert state["source"] == "migrated_from_library_ACTIVE_DECISION_CONTEXT_V2"
    assert state["source_provenance_class"] == "HISTORICAL_MIGRATION_ONLY"


def test_p1_7_introduction_state_cannot_masquerade_as_current_capability_or_execution():
    import json

    state = json.loads((ROOT / "control/fpl_master_v12/FPL_MASTER_STATE_V12.json").read_text(encoding="utf-8"))
    registry = state["model_evidence"]["p1_7_parameter_registry"]

    for stale_live_key in (
        "covariance_status",
        "monte_carlo_started",
        "package_optimizer_started_by_p1_7",
        "mini_league_overlay_started",
    ):
        assert stale_live_key not in registry

    intro = registry["introduction_state"]
    assert intro["semantic_scope"] == "HISTORICAL_P1_7_INTRODUCTION_ONLY"
    assert intro["covariance_status"] == "COVARIANCE_NOT_MODELLED_YET"
    assert intro["monte_carlo_started"] is False
    assert intro["package_optimizer_started_by_p1_7"] is False
    assert intro["mini_league_overlay_started"] is False
    assert intro["occurrence_execution_proof"] is False

    capabilities = registry["current_capability_references"]
    assert capabilities["monte_carlo_owner"] == "src/engines/v12_monte_carlo.py"
    assert capabilities["package_search_owner"] == "src/engines/v12_package_search.py"
    assert capabilities["mini_league_overlay_stage"] == "P1.8"
    assert capabilities["capability_exists_not_occurrence_execution_proof"] is True
    assert (ROOT / capabilities["monte_carlo_owner"]).exists()
    assert (ROOT / capabilities["package_search_owner"]).exists()
