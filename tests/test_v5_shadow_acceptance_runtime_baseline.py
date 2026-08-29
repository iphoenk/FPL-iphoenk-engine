from src.v5 import V5_VERSION
from src.v5.shadow_acceptance import _baseline, _current_release_fingerprint, validated_cycle_eligible


def _payload(v3_engine_version: str):
    baseline_version, baseline_sha = _baseline()
    return {
        "mode": "REAL_SHADOW",
        "acceptance_progress": {"cycle_pass": True},
        "post_validation": {"status": "PASS"},
        "acceptance_context": {
            "production_baseline_version": baseline_version,
            "production_main_sha": baseline_sha,
            "release_fingerprint": _current_release_fingerprint(),
        },
        "v3": {"engine_version": v3_engine_version},
        "v5": {"engine_version": V5_VERSION},
        "operational_invariants": {"pass": True},
        "parity": {"pass": True},
    }


def test_current_v3_runtime_version_can_be_newer_than_frozen_football_truth_baseline():
    baseline_version, _ = _baseline()
    assert baseline_version == "v3.20.0"
    assert validated_cycle_eligible(_payload("3.25.0")) is True


def test_wrong_production_sha_still_fails_closed():
    payload = _payload("3.25.0")
    payload["acceptance_context"]["production_main_sha"] = "not-the-accepted-production-sha"
    assert validated_cycle_eligible(payload) is False
