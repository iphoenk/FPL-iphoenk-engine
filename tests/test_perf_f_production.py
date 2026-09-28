from src.engines.v12_cache_operational import plan_cache_behavior
from src.engines.v12_perf_f_production import (
    PerfFProductionError,
    build_production_sample,
    canonical_required_timings,
    validate_production_sample,
)


def proof():
    return {
        "monte_carlo": {"actual_paths": 500000, "canonical_pass": True},
        "stages": [
            {"stage": "P1_1_P1_3_FULL_UNIVERSE", "status": "PASS", "elapsed_seconds": 1.2},
            {"stage": "P1_7_LINEUP", "status": "PASS", "elapsed_seconds": 0.4},
            {"stage": "P1_4_MONTE_CARLO", "status": "PASS", "elapsed_seconds": 2.3},
            {"stage": "P1_2_PACKAGE_UTILITY", "status": "PASS", "elapsed_seconds": 9.9},
        ],
    }


def worker(case="NO_CHANGE"):
    keys = [] if case in {"NO_CHANGE", "P4_SCENARIO_HIT"} else ["test:key"]
    plan = plan_cache_behavior(case, affected_dependency_keys=keys)
    return {
        "t0": 100.0,
        "t1": 103.0,
        "change_class": case,
        "expected_cache_state": dict(plan.expected),
        "actual_cache_state": dict(plan.expected),
        "invalidated_dependency_keys": keys,
        "cache_correctness": "PASS",
        "cache_performance": "PASS",
        "warm_semantic_fingerprint": "f" * 64,
        "private_delivery_status": "PASS",
        "private_remote_sha": "c" * 40,
        "timings": {
            "classification": 0.01,
            "cache_lookup": 0.01,
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


def test_collector_uses_exact_canonical_stage_rows_not_package_wall_time():
    timings = canonical_required_timings(proof())
    assert timings == {"Stage2": 1.2, "P1.7": 0.4, "MC": 2.3}


def test_build_sample_carries_production_lineage_and_private_receipt():
    sample = build_production_sample(
        case="NO_CHANGE",
        worker_result=worker(),
        execution_proof=proof(),
        cold_semantic_fingerprint="f" * 64,
        scenario_seconds=0.0,
    )
    assert sample.private_remote_sha == "c" * 40
    assert sample.owner_context_fingerprint == "owner"
    assert sample.timings["Stage2"] == 1.2


def test_validated_production_sample_passes_only_complete_contract():
    out = validate_production_sample(
        case="NO_CHANGE",
        worker_result=worker(),
        execution_proof=proof(),
        cold_semantic_fingerprint="f" * 64,
        scenario_seconds=0.0,
    )
    assert out["status"] == "PASS"
    assert out["private_publish_pass"] is True
    assert out["cache_correctness_pass"] is True


def test_mc_below_authority_is_rejected():
    bad = proof()
    bad["monte_carlo"]["actual_paths"] = 499999
    try:
        canonical_required_timings(bad)
    except PerfFProductionError:
        pass
    else:
        raise AssertionError("expected PerfFProductionError")
