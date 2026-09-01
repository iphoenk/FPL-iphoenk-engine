from __future__ import annotations

import json

import pytest

from src.runtime_v3 import main_pr_provenance as provenance


TEMP_V4_PATH = ".github/workflows/v4-perf-attestation-refresh-temp.yml"
SHARED_V3_PATH = "src/runtime_v3/domain_orchestrator.py"
EXPECTED_HISTORICAL = {
    "38fa0e64d2c35afea7d82f2ef8170b6417866c43": {TEMP_V4_PATH},
    "1580270d16f3ba8b5d349bb2eb97d13617d5f04b": {TEMP_V4_PATH},
    "9eba3392f58e1ce2f1597bf64732afc33cebed1e": {
        ".github/workflows/v4-validation-integrity-dedup-temp.yml"
    },
    "c6c0c1f89df35d810313edbbadd0debe23bbdf6b": {
        ".github/workflows/v4-validation-integrity-dedup-temp.yml"
    },
}


def _direct_push_error(sha: str) -> RuntimeError:
    return RuntimeError(
        f"REFUSING_DIRECT_MAIN_PUSH_WITHOUT_MERGED_PR source_commit={sha} branch=main"
    )


def _commit(parent: str, *paths: str) -> dict:
    return {
        "parents": [{"sha": parent}],
        "files": [{"filename": path} for path in paths],
    }


def test_history_allows_exact_historical_sha_and_exact_paths(monkeypatch):
    head = "a" * 40
    anchor = "b" * 40
    monkeypatch.setattr(
        provenance,
        "verify_main_commit_pr_provenance",
        lambda **_kwargs: (_ for _ in ()).throw(_direct_push_error(head)),
    )
    monkeypatch.setattr(
        provenance,
        "_fetch_commit_payload",
        lambda **_kwargs: _commit(anchor, TEMP_V4_PATH),
    )

    result = provenance.verify_main_history_pr_provenance(
        api_url="https://api.github.com",
        repository="iphoenk/FPL-iphoenk-engine",
        sha=head,
        branch="main",
        token="token",
        trust_anchor_sha=anchor,
        historical_direct_commit_attestations={head: {TEMP_V4_PATH}},
    )

    assert result["status"] == "PASS"
    assert result["version_exclusive_direct_commits"] == []
    assert result["historical_direct_attested_commits"] == [
        {
            "sha": head,
            "provenance": "HISTORICAL_VERSION_EXCLUSIVE_DIRECT_ATTESTED",
            "pull_request": None,
            "merged_at": None,
            "paths": [TEMP_V4_PATH],
        }
    ]


def test_history_rejects_historical_sha_when_actual_paths_drift(monkeypatch):
    head = "a" * 40
    anchor = "b" * 40
    monkeypatch.setattr(
        provenance,
        "verify_main_commit_pr_provenance",
        lambda **_kwargs: (_ for _ in ()).throw(_direct_push_error(head)),
    )
    monkeypatch.setattr(
        provenance,
        "_fetch_commit_payload",
        lambda **_kwargs: _commit(anchor, TEMP_V4_PATH, SHARED_V3_PATH),
    )

    with pytest.raises(
        RuntimeError,
        match="MAIN_PROVENANCE_HISTORICAL_ATTESTATION_PATH_MISMATCH",
    ):
        provenance.verify_main_history_pr_provenance(
            api_url="https://api.github.com",
            repository="iphoenk/FPL-iphoenk-engine",
            sha=head,
            branch="main",
            token="token",
            trust_anchor_sha=anchor,
            historical_direct_commit_attestations={head: {TEMP_V4_PATH}},
        )


def test_policy_historical_attestations_are_exact_sha_scoped_and_retired_v4_only():
    policy = provenance._load_policy()
    actual = provenance._historical_attestation_map(policy)

    assert actual == EXPECTED_HISTORICAL
    assert set(actual).isdisjoint(set(policy["version_exclusive_paths"]))
    assert all(provenance._SHA40.fullmatch(sha) for sha in actual)
    assert all(
        path.startswith(".github/workflows/v4-") and path.endswith(".yml")
        for paths in actual.values()
        for path in paths
    )
    assert all(
        path not in set(policy["version_exclusive_paths"])
        for paths in actual.values()
        for path in paths
    )


def test_policy_rejects_historical_wildcard(tmp_path):
    policy = provenance._load_policy().copy()
    policy["historical_direct_commit_attestations"] = [
        {
            "sha": "a" * 40,
            "paths": [".github/workflows/v4-*.yml"],
            "reason": "invalid broad historical scope",
        }
    ]
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match="MAIN_PROVENANCE_POLICY_HISTORICAL_PATHS_MUST_BE_EXACT",
    ):
        provenance._load_policy(path)


def test_policy_rejects_historical_v3_or_shared_path(tmp_path):
    policy = provenance._load_policy().copy()
    policy["historical_direct_commit_attestations"] = [
        {
            "sha": "a" * 40,
            "paths": [SHARED_V3_PATH],
            "reason": "invalid shared scope",
        }
    ]
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match="MAIN_PROVENANCE_POLICY_HISTORICAL_SCOPE_TOO_BROAD",
    ):
        provenance._load_policy(path)
