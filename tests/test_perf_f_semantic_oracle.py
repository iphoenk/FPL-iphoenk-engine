from src.engines.v12_cache_operational import plan_cache_behavior
from src.engines.v12_perf_f import PerfFSample, summarize_samples, validate_sample
from src.engines.v12_semantic_oracle import (
    compare_warm_cold,
    semantic_component_fingerprints,
    semantic_fingerprint,
    semantic_subcomponent_fingerprints,
)


def semantic(action="WAIT"):
    return {
        "report": {
            "S08": {"captain": 1, "vice": 2},
            "S11": {"watchlist": [10, 20]},
            "S12": {"rise": [10]},
            "S13": {"fall": [30]},
            "S15B": {"eo": {"1": 1.4}},
            "S19": {"action": action},
        },
        "transfer_action": action,
        "xi": list(range(1, 12)),
        "bench": [12, 13, 14, 15],
        "route": "HOLD",
        "p1_7": {"captain": 1, "vice": 2},
        "monte_carlo": {"decision": "HOLD"},
        "final_decision_state": action,
        "generated_at": "ignored",
    }


def lineage():
    return {
        "production_sha": "a" * 40,
        "runtime_data_sha": "b" * 40,
        "runtime_class": "NORMALIZED",
        "model_version": "V12",
        "schema_version": "6",
        "gw_fixture_fingerprint": "gw6",
        "projection_lineage_fingerprint": "proj",
        "current15_fingerprint": "our15",
        "mc_authority": "V12_MC_500K_CRN",
    }


def timings():
    return {
        "classification": 0.01,
        "cache_lookup": 0.01,
        "Stage2": 0.0,
        "P1.7": 0.0,
        "MC": 0.0,
        "scenario": 0.0,
        "Stage3": 0.2,
        "render": 0.2,
        "QA": 0.2,
        "private_publish": 0.2,
    }


def sample(case, total=1.0, equal=True, *, private_pass=True, wrong_hit=False):
    cold = semantic()
    warm = semantic() if equal else semantic("TRANSFER")
    keys = [] if case in {"NO_CHANGE", "P4_SCENARIO_HIT"} else ["test:key"]
    plan = plan_cache_behavior(case, affected_dependency_keys=keys)
    actual = dict(plan.expected)
    if wrong_hit:
        target = next(
            layer for layer, state in plan.expected.items()
            if state == "MISS"
        )
        actual[target] = "HIT"
    return PerfFSample(
        case=case,
        t0=100.0,
        t1=100.0 + total,
        lineage=lineage(),
        change_class=case,
        expected_cache_state=dict(plan.expected),
        actual_cache_state=actual,
        invalidated_dependency_keys=keys,
        timings=timings(),
        cold_semantic_fingerprint=semantic_fingerprint(cold),
        warm_semantic_fingerprint=semantic_fingerprint(warm),
        owner_context_fingerprint="owner-private",
        reused_dependency_keys={},
        private_delivery_status="PASS" if private_pass else "FAIL",
        private_remote_sha=("c" * 40) if private_pass else "",
    )


def test_oracle_ignores_timestamps_but_catches_decision_change():
    left = semantic()
    right = semantic()
    right["generated_at"] = "different"
    assert compare_warm_cold(warm=left, cold=right)["equal"] is True
    assert compare_warm_cold(warm=semantic("TRANSFER"), cold=semantic())["equal"] is False


def test_latency_pass_never_overrides_semantic_inequality():
    out = validate_sample(sample("NO_CHANGE", total=0.5, equal=False))
    assert out["latency_pass"] is True
    assert out["status"] == "FAIL"
    assert out["reason"] == "SEMANTIC_INEQUALITY"


def test_cache_wrong_hit_and_private_publish_are_hard_failures():
    cache = validate_sample(sample("MATERIAL_PROJECTION", wrong_hit=True))
    assert cache["status"] == "FAIL"
    assert cache["reason"] == "CACHE_CORRECTNESS_FAIL"
    private = validate_sample(sample("NO_CHANGE", private_pass=False))
    assert private["status"] == "FAIL"
    assert private["reason"] == "PRIVATE_PUBLISH_FAIL"


def test_transfer_action_is_part_of_semantic_surface():
    warm = semantic()
    cold = semantic()
    cold["transfer_action"] = "TRANSFER"
    assert compare_warm_cold(warm=warm, cold=cold)["equal"] is False


def test_over_15s_fails_even_with_semantic_equality():
    out = validate_sample(sample("PRICE_ONLY", total=15.001, equal=True))
    assert out["semantic_equal"] is True
    assert out["status"] == "FAIL"


def test_summary_does_not_average_away_failing_sample():
    cases = [
        "NO_CHANGE", "MINI_LEAGUE_ONLY", "PRICE_ONLY", "OUR15_AVAILABILITY",
        "CAPTAIN_CHANGE", "VICE_CAPTAIN_CHANGE", "MATERIAL_PROJECTION",
        "P4_SCENARIO_HIT", "P4_SCENARIO_MISS",
    ]
    samples = [sample(case, total=1.0) for case in cases]
    samples.append(sample("PRICE_ONLY", total=16.0))
    summary = summarize_samples(samples)
    assert summary["cases"]["PRICE_ONLY"]["median_seconds"] <= 15.0
    assert summary["cases"]["PRICE_ONLY"]["max_seconds"] == 16.0
    assert summary["cases"]["PRICE_ONLY"]["status"] == "FAIL"
    assert summary["all_required_cases_green"] is False


def test_oracle_reads_real_integrated_report_sections_shape():
    payload = {
        "report": {
            "sections": [
                {"section_id": "S08", "content": {"captain": 1, "vice": 2}},
                {"section_id": "S11", "content": {"watchlist": [10]}},
                {"section_id": "S12", "content": {"rise": [10]}},
                {"section_id": "S13", "content": {"fall": [30]}},
                {"section_id": "S15B", "content": {"eo": {"1": 1.4}}},
                {"section_id": "S19", "content": {"action": "WAIT"}},
            ]
        },
        "generated_at": "ignored",
    }
    assert semantic_fingerprint(payload)
    assert compare_warm_cold(warm=payload, cold=payload)["equal"] is True


def test_component_fingerprints_localize_semantic_difference_without_payload():
    warm = semantic()
    cold = semantic()
    cold["report"]["S12"] = {"rise": [99]}
    warm_parts = semantic_component_fingerprints(warm)
    cold_parts = semantic_component_fingerprints(cold)
    mismatches = sorted(
        key for key in set(warm_parts) | set(cold_parts)
        if warm_parts.get(key) != cold_parts.get(key)
    )
    assert mismatches == ["report_sections.S12"]
    assert all(len(value) == 64 for value in warm_parts.values())


def test_subcomponent_fingerprints_localize_nested_difference_without_payload():
    warm = semantic()
    cold = semantic()
    cold["report"]["S15B"] = {
        "eo": {"1": 1.4},
        "mini_overlay": {"captain": 2},
    }
    warm["report"]["S15B"] = {
        "eo": {"1": 1.4},
        "mini_overlay": {"captain": 1},
    }
    warm_parts = semantic_subcomponent_fingerprints(
        warm, "report_sections.S15B"
    )
    cold_parts = semantic_subcomponent_fingerprints(
        cold, "report_sections.S15B"
    )
    mismatches = sorted(
        key for key in set(warm_parts) | set(cold_parts)
        if warm_parts.get(key) != cold_parts.get(key)
    )
    assert mismatches == ["mini_overlay"]
    assert warm_parts["eo"] == cold_parts["eo"]
    assert all(len(value) == 64 for value in warm_parts.values())
