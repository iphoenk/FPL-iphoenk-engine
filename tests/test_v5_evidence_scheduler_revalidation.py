from scripts.v5_evidence_scheduler_gate import operational_revalidation_reasons


CURRENT_SHA = "1" * 40
CURRENT_FP = "sha256:" + "2" * 64
CURRENT_VERSION = "5.0.0-beta.4"
REQUIRED = 3


def summary(**overrides):
    payload = {
        "production_main_sha": CURRENT_SHA,
        "release_fingerprint": CURRENT_FP,
        "v5_version": CURRENT_VERSION,
        "required_validated_cycles": REQUIRED,
        "validated_successful_cycles": REQUIRED,
        "operational_candidate_eligible": True,
    }
    payload.update(overrides)
    return payload


def reasons(payload):
    return operational_revalidation_reasons(
        payload,
        deployed_runtime_sha=CURRENT_SHA,
        current_release_fingerprint=CURRENT_FP,
        current_v5_version=CURRENT_VERSION,
        required_cycles=REQUIRED,
    )


def test_current_complete_operational_evidence_requires_no_revalidation():
    assert reasons(summary()) == []


def test_missing_operational_evidence_fails_closed():
    assert reasons({}) == ["OPERATIONAL_ACCEPTANCE_MISSING"]


def test_production_runtime_reanchor_requires_fresh_shadow_evidence():
    assert "PRODUCTION_REANCHOR_REVALIDATION" in reasons(summary(production_main_sha="3" * 40))


def test_v5_release_change_requires_fresh_shadow_evidence():
    assert "V5_RELEASE_REVALIDATION" in reasons(summary(release_fingerprint="sha256:" + "4" * 64))
    assert "V5_RELEASE_REVALIDATION" in reasons(summary(v5_version="5.0.0-beta.next"))


def test_incomplete_cycles_keep_scheduler_revalidation_active():
    result = reasons(summary(validated_successful_cycles=1, operational_candidate_eligible=False))
    assert "OPERATIONAL_ACCEPTANCE_INCOMPLETE" in result


def test_acceptance_policy_drift_fails_closed():
    result = reasons(summary(required_validated_cycles=2))
    assert "OPERATIONAL_ACCEPTANCE_POLICY_DRIFT" in result
