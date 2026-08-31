import pytest

from src.engines.production_contract_validate import _validate_official_runtime_evidence


def _fresh_runtime(cache_entries=1):
    return {
        "execution_profile": "fast_decision",
        "shared_official_cache_entries": cache_entries,
        "profile_config": {"reuse_services": {}},
        "services": {"official_snapshot": {"status": "SUCCESS"}},
    }


def _reused_runtime(**overrides):
    official = {
        "status": "REUSED",
        "reuse_mode": "AGE_TTL",
        "reuse_freshness_source": "SEMANTIC_TIMESTAMP",
        "reuse_freshness_artifact": "official_snapshot.json",
        "reuse_freshness_field": "generated_at",
        "reuse_age_seconds": 12.5,
        "workspace_retry_restored": True,
        "workspace_retry_artifact": "official_snapshot.retry.json",
        "artifact_validation": [{"artifact": "official_snapshot.json", "validation": "PARSE_ONLY"}],
    }
    official.update(overrides)
    return {
        "execution_profile": "fast_decision",
        "shared_official_cache_entries": 0,
        "profile_config": {
            "reuse_services": {
                "official_snapshot": {
                    "max_age_seconds": 60,
                    "freshness_artifact": "official_snapshot.json",
                    "freshness_field": "generated_at",
                    "workspace_retry_artifact": "official_snapshot.retry.json",
                }
            }
        },
        "services": {"official_snapshot": official},
    }


def test_fresh_official_run_still_requires_shared_http_cache_evidence():
    _validate_official_runtime_evidence(_fresh_runtime(cache_entries=3))
    with pytest.raises(AssertionError):
        _validate_official_runtime_evidence(_fresh_runtime(cache_entries=0))


def test_true_warm_retry_accepts_zero_http_cache_when_snapshot_is_semantically_reused():
    runtime = _reused_runtime()
    _validate_official_runtime_evidence(runtime)


def test_warm_retry_rejects_dead_or_unbounded_reuse_claims():
    with pytest.raises(AssertionError):
        _validate_official_runtime_evidence(_reused_runtime(workspace_retry_restored=False))
    with pytest.raises(AssertionError):
        _validate_official_runtime_evidence(_reused_runtime(reuse_age_seconds=61.0))
    with pytest.raises(AssertionError):
        _validate_official_runtime_evidence(_reused_runtime(reuse_mode="CONTENT_ADDRESSED"))


def test_warm_retry_rejects_wrong_profile_or_retry_mirror():
    runtime = _reused_runtime()
    runtime["execution_profile"] = "live"
    with pytest.raises(AssertionError):
        _validate_official_runtime_evidence(runtime)

    with pytest.raises(AssertionError):
        _validate_official_runtime_evidence(_reused_runtime(workspace_retry_artifact="other.json"))
