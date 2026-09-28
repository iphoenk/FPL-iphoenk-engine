import pytest

from src.engines.v12_cache_operational import plan_cache_behavior
from src.engines.v12_perf_f_production import (
    PerfFProductionError,
    build_production_sample,
    canonical_p17_timings,
    canonical_required_timings,
    validate_production_sample,
)


def proof():
    return {
        "monte_carlo": {"actual_paths": 500000, "canonical_pass": True},
        "stages": [
            {
                "stage": "P1_1_P1_3_FULL_UNIVERSE",
                "status": "PASS",
                "elapsed_seconds": 1.2,
            },
            {
                "stage": "P1_7_LINEUP",
                "status": "PASS",
                "elapsed_seconds": 0.4,
            },
            {
                "stage": "P1_4_MONTE_CARLO",
                "status": "PASS",
                "elapsed_seconds": 2.3,
            },
            {
                "stage": "P1_2_PACKAGE_UTILITY",
                "status": "PASS",
                "elapsed_seconds": 9.9,
            },
        ],
        "p1_7_execution": {
            "lineup": {
                "stage": "P1_7_LINEUP",
                "status": "PASS",
                "elapsed_seconds": 0.4,
            },
            "direct_package": {
                "execution_mode": "CROSS_ROUTE_FAMILY_NUMPY_EXACT_P1_7",
                "elapsed_seconds": 3.1,
                "lossy_pruning": False,
                "p1_7_math_mutated": False,
            },
            "funded_package": {
                "execution_mode": "CROSS_ROUTE_FAMILY_NUMPY_EXACT_P1_7",
                "elapsed_seconds": 1.7,
                "lossy_pruning": False,
                "p1_7_math_mutated": False,
            },
        },
    }


def worker(case="NO_CHANGE", *, actual_override=None):
    keys = [] if case in {"NO_CHANGE", "P4_SCENARIO_HIT"} else ["test:key"]
    plan = plan_cache_behavior(case, affected_dependency_keys=keys)
    actual = dict(plan.expected)
    if actual_override:
        actual.update(actual_override)
    return {
        "t0": 100.0,
        "t1": 103.0,
        "change_class": case,
        "expected_cache_state": dict(plan.expected),
        "actual_cache_state": actual,
        "invalidated_dependency_keys": keys,
        "reused_dependency_keys": {},
        "cache_correctness": "PASS",
        "cache_performance": "PASS",
        "warm_semantic_fingerprint": "f" * 64,
        "private_delivery_status": "PASS",
        "private_remote_sha": "c" * 40,
        "timings": {
            "classification": 0.01,
            "cache_lookup": 0.01,
            "scenario": 0.0,
            "recompute": 2.0,
            "Stage3": 0.1,
            "render": 0.1,
            "QA": 0.1,
            "private_publish": 0.2,
        },
        "final_identity": {
            "production_sha": "a" * 40,
            "runtime_data_sha": "b" * 40,
            "runtime_class": "NORMALIZED",
            "model_version": "FPL_MASTER_V12:" + "a" * 40,
            "schema_version": "V12_CACHE_OPERATIONAL_V1",
            "gw_fixture_fingerprint": "gw",
            "projection_lineage_fingerprint": "proj",
            "current15_fingerprint": "our15",
            "owner_context_fingerprint": "owner",
            "mc_authority": "V12_MC_500K_CRN",
        },
    }


def test_collector_uses_exact_owner_p17_proofs_not_package_wall_time():
    p17 = canonical_p17_timings(proof())
    assert p17 == {
        "lineup": 0.4,
        "direct_package": 3.1,
        "funded_package": 1.7,
        "total": pytest.approx(5.2),
    }
    timings = canonical_required_timings(proof())
    assert timings["Stage2"] == 1.2
    assert timings["P1.7"] == pytest.approx(5.2)
    assert timings["MC"] == 2.3
    assert timings["P1.7"] != 9.9


def test_hit_layers_are_zero_in_warm_phase_accounting():
    sample = build_production_sample(
        case="NO_CHANGE",
        worker_result=worker(),
        execution_proof=proof(),
        cold_semantic_fingerprint="f" * 64,
    )
    assert sample.private_remote_sha == "c" * 40
    assert sample.owner_context_fingerprint == "owner"
    assert sample.timings["Stage2"] == 0.0
    assert sample.timings["P1.7"] == 0.0
    assert sample.timings["MC"] == 0.0


def test_real_miss_uses_exact_canonical_owner_timing():
    sample = build_production_sample(
        case="MATERIAL_PROJECTION",
        worker_result=worker("MATERIAL_PROJECTION"),
        execution_proof=proof(),
        cold_semantic_fingerprint="f" * 64,
    )
    assert sample.timings["Stage2"] == 1.2
    assert sample.timings["P1.7"] == pytest.approx(5.2)
    assert sample.timings["MC"] == 2.3


def test_partial_invalidation_without_exact_warm_timing_is_rejected():
    row = worker("PRICE_ONLY")
    assert row["actual_cache_state"]["MC"] == "PARTIAL_INVALIDATION"
    with pytest.raises(
        PerfFProductionError,
        match="partial invalidation requires exact warm timing",
    ):
        build_production_sample(
            case="PRICE_ONLY",
            worker_result=row,
            execution_proof=proof(),
            cold_semantic_fingerprint="f" * 64,
        )


def test_validated_no_change_production_sample_passes_complete_contract():
    out = validate_production_sample(
        case="NO_CHANGE",
        worker_result=worker(),
        execution_proof=proof(),
        cold_semantic_fingerprint="f" * 64,
    )
    assert out["status"] == "PASS"
    assert out["private_publish_pass"] is True
    assert out["cache_correctness_pass"] is True


def test_mc_below_authority_is_rejected():
    bad = proof()
    bad["monte_carlo"]["actual_paths"] = 499999
    with pytest.raises(PerfFProductionError):
        canonical_required_timings(bad)


def test_missing_exact_package_p17_proof_is_rejected():
    bad = proof()
    bad["p1_7_execution"]["direct_package"] = None
    with pytest.raises(PerfFProductionError, match="missing exact P1.7 owner proof"):
        canonical_p17_timings(bad)


def test_partial_invalidation_accepts_explicit_zero_warm_mc_timing():
    row = worker("PRICE_ONLY")
    row["layer_timings"] = {"MC": 0.0}
    sample = build_production_sample(
        case="PRICE_ONLY",
        worker_result=row,
        execution_proof=proof(),
        cold_semantic_fingerprint="f" * 64,
    )
    assert sample.timings["Stage2"] == 0.0
    assert sample.timings["P1.7"] == 0.0
    assert sample.timings["MC"] == 0.0
