from __future__ import annotations

import json

import pytest

from src.runtime_v3 import main_pr_provenance as provenance


ALLOWED_V4_PATH = ".github/workflows/v4-prediction.yml"
SHARED_V3_PATH = "src/runtime_v3/domain_orchestrator.py"


def _direct_push_error(sha: str) -> RuntimeError:
    return RuntimeError(f"REFUSING_DIRECT_MAIN_PUSH_WITHOUT_MERGED_PR source_commit={sha} branch=main")


def _commit(parent: str, *paths: str) -> dict:
    return {
        "parents": [{"sha": parent}],
        "files": [{"filename": path} for path in paths],
    }


def test_select_merged_pr_prefers_latest_matching_base():
    payload = [
        {"number": 1, "state": "closed", "merged_at": "2026-08-20T00:00:00Z", "base": {"ref": "main"}},
        {"number": 2, "state": "closed", "merged_at": "2026-08-21T00:00:00Z", "base": {"ref": "main"}},
        {"number": 3, "state": "closed", "merged_at": "2026-08-22T00:00:00Z", "base": {"ref": "other"}},
    ]
    assert provenance._select_merged_pr(payload, branch="main")["number"] == 2


def test_select_merged_pr_rejects_non_list_payload():
    with pytest.raises(RuntimeError, match="MAIN_PR_PROVENANCE_INVALID_GITHUB_RESPONSE"):
        provenance._select_merged_pr({}, branch="main")


def test_select_merged_pr_requires_actual_merge():
    with pytest.raises(RuntimeError, match="MAIN_PR_PROVENANCE_NO_MERGED_PR"):
        provenance._select_merged_pr(
            [{"number": 1, "state": "closed", "merged_at": None, "base": {"ref": "main"}}],
            branch="main",
        )


def test_verify_commit_refuses_direct_main_push(monkeypatch):
    monkeypatch.setattr(provenance, "_github_json", lambda *_args, **_kwargs: [])
    with pytest.raises(RuntimeError, match="REFUSING_DIRECT_MAIN_PUSH_WITHOUT_MERGED_PR"):
        provenance.verify_main_commit_pr_provenance(
            api_url="https://api.github.com",
            repository="iphoenk/FPL-iphoenk-engine",
            sha="a" * 40,
            branch="main",
            token="token",
        )


def test_verify_commit_returns_merged_pr(monkeypatch):
    monkeypatch.setattr(
        provenance,
        "_github_json",
        lambda *_args, **_kwargs: [
            {
                "number": 123,
                "state": "closed",
                "merged_at": "2026-08-31T00:00:00Z",
                "base": {"ref": "main"},
            }
        ],
    )
    result = provenance.verify_main_commit_pr_provenance(
        api_url="https://api.github.com",
        repository="iphoenk/FPL-iphoenk-engine",
        sha="a" * 40,
        branch="main",
        token="token",
    )
    assert result["status"] == "PASS"
    assert result["pull_request"] == 123


def test_history_verifier_walks_first_parent_to_anchor(monkeypatch):
    head = "a" * 40
    parent = "b" * 40
    anchor = "c" * 40

    def fake_verify(**kwargs):
        return {"status": "PASS", "pull_request": 100 if kwargs["sha"] == head else 99, "merged_at": "x"}

    def fake_github(url, _token):
        if url.endswith(head):
            return {"parents": [{"sha": parent}]}
        if url.endswith(parent):
            return {"parents": [{"sha": anchor}]}
        raise AssertionError(url)

    monkeypatch.setattr(provenance, "verify_main_commit_pr_provenance", fake_verify)
    monkeypatch.setattr(provenance, "_github_json", fake_github)
    result = provenance.verify_main_history_pr_provenance(
        api_url="https://api.github.com",
        repository="iphoenk/FPL-iphoenk-engine",
        sha=head,
        branch="main",
        token="token",
        trust_anchor_sha=anchor,
    )
    assert result["status"] == "PASS"
    assert result["commits_checked"] == 2
    assert result["head_pull_request"] == 100
    assert result["first_parent_chain_integrity"] is True


def test_history_verifier_fails_on_untrusted_ancestor(monkeypatch):
    head = "a" * 40
    bad = "b" * 40
    anchor = "c" * 40

    def fake_verify(**kwargs):
        if kwargs["sha"] == bad:
            raise _direct_push_error(bad)
        return {"status": "PASS", "pull_request": 100, "merged_at": "x"}

    monkeypatch.setattr(provenance, "verify_main_commit_pr_provenance", fake_verify)
    monkeypatch.setattr(provenance, "_github_json", lambda *_args, **_kwargs: {"parents": [{"sha": bad}]})
    with pytest.raises(RuntimeError, match="MAIN_PROVENANCE_UNTRUSTED_ANCESTOR"):
        provenance.verify_main_history_pr_provenance(
            api_url="https://api.github.com",
            repository="iphoenk/FPL-iphoenk-engine",
            sha=head,
            branch="main",
            token="token",
            trust_anchor_sha=anchor,
        )


def test_history_verifier_allows_only_strict_version_exclusive_direct_commit(monkeypatch):
    head = "a" * 40
    anchor = "b" * 40
    monkeypatch.setattr(provenance, "verify_main_commit_pr_provenance", lambda **_kwargs: (_ for _ in ()).throw(_direct_push_error(head)))
    monkeypatch.setattr(provenance, "_fetch_commit_payload", lambda **_kwargs: _commit(anchor, ALLOWED_V4_PATH))

    result = provenance.verify_main_history_pr_provenance(
        api_url="https://api.github.com",
        repository="iphoenk/FPL-iphoenk-engine",
        sha=head,
        branch="main",
        token="token",
        trust_anchor_sha=anchor,
        allow_direct_version_exclusive_commits=True,
        version_exclusive_paths={ALLOWED_V4_PATH},
    )

    assert result["status"] == "PASS"
    assert result["version_exclusive_direct_commits"] == [
        {
            "sha": head,
            "provenance": "VERSION_EXCLUSIVE_DIRECT",
            "pull_request": None,
            "merged_at": None,
            "paths": [ALLOWED_V4_PATH],
        }
    ]


def test_history_verifier_rejects_mixed_direct_commit(monkeypatch):
    head = "a" * 40
    anchor = "b" * 40
    monkeypatch.setattr(provenance, "verify_main_commit_pr_provenance", lambda **_kwargs: (_ for _ in ()).throw(_direct_push_error(head)))
    monkeypatch.setattr(
        provenance,
        "_fetch_commit_payload",
        lambda **_kwargs: _commit(anchor, ALLOWED_V4_PATH, SHARED_V3_PATH),
    )

    with pytest.raises(RuntimeError, match="MAIN_PROVENANCE_UNTRUSTED_ANCESTOR"):
        provenance.verify_main_history_pr_provenance(
            api_url="https://api.github.com",
            repository="iphoenk/FPL-iphoenk-engine",
            sha=head,
            branch="main",
            token="token",
            trust_anchor_sha=anchor,
            allow_direct_version_exclusive_commits=True,
            version_exclusive_paths={ALLOWED_V4_PATH},
        )


def test_version_scope_advance_allows_multiple_strict_version_exclusive_commits(monkeypatch):
    head = "a" * 40
    parent = "b" * 40
    source = "c" * 40
    payloads = {
        head: _commit(parent, ALLOWED_V4_PATH),
        parent: _commit(source, ALLOWED_V4_PATH),
    }
    monkeypatch.setattr(provenance, "_fetch_commit_payload", lambda **kwargs: payloads[kwargs["sha"]])

    result = provenance.verify_version_exclusive_main_advance(
        api_url="https://api.github.com",
        repository="iphoenk/FPL-iphoenk-engine",
        source_sha=source,
        head_sha=head,
        token="token",
        version_exclusive_paths={ALLOWED_V4_PATH},
    )

    assert result["status"] == "PASS"
    assert result["commits_checked"] == 2
    assert [row["sha"] for row in result["verified_commits"]] == [head, parent]


def test_version_scope_advance_rejects_shared_or_v3_change(monkeypatch):
    head = "a" * 40
    source = "b" * 40
    monkeypatch.setattr(
        provenance,
        "_fetch_commit_payload",
        lambda **_kwargs: _commit(source, ALLOWED_V4_PATH, SHARED_V3_PATH),
    )

    with pytest.raises(RuntimeError, match="V3_VERSION_SCOPE_REFUSING_STALE_SOURCE"):
        provenance.verify_version_exclusive_main_advance(
            api_url="https://api.github.com",
            repository="iphoenk/FPL-iphoenk-engine",
            source_sha=source,
            head_sha=head,
            token="token",
            version_exclusive_paths={ALLOWED_V4_PATH},
        )


def test_history_verifier_requires_anchor():
    with pytest.raises(RuntimeError, match="MAIN_PROVENANCE_MISSING_TRUST_ANCHOR"):
        provenance.verify_main_history_pr_provenance(
            api_url="https://api.github.com",
            repository="iphoenk/FPL-iphoenk-engine",
            sha="a" * 40,
            branch="main",
            token="token",
            trust_anchor_sha="",
        )


def test_history_verifier_rejects_invalid_commit_response(monkeypatch):
    head = "a" * 40
    anchor = "b" * 40
    monkeypatch.setattr(
        provenance,
        "verify_main_commit_pr_provenance",
        lambda **_kwargs: {"status": "PASS", "pull_request": 1, "merged_at": "x"},
    )
    monkeypatch.setattr(provenance, "_github_json", lambda *_args, **_kwargs: [])
    with pytest.raises(RuntimeError, match="MAIN_PROVENANCE_INVALID_COMMIT_RESPONSE"):
        provenance.verify_main_history_pr_provenance(
            api_url="https://api.github.com",
            repository="iphoenk/FPL-iphoenk-engine",
            sha=head,
            branch="main",
            token="token",
            trust_anchor_sha=anchor,
        )


def test_policy_is_registry_owned_and_version_scope_is_exact():
    policy = provenance._load_policy()
    assert policy["registry"] == "V3_MAIN_PROVENANCE_POLICY_V1"
    assert policy["branch"] == "main"
    assert provenance._SHA40.fullmatch(policy["trust_anchor_sha"])
    assert policy["require_anchor_in_first_parent_history"] is True
    assert policy["require_each_first_parent_commit_after_anchor_from_merged_pr"] is True
    assert policy["fail_closed_on_github_api_error"] is True
    assert policy["allow_direct_version_exclusive_commits"] is True
    assert policy["version_exclusive_direct_commit_requires_all_changed_paths_allowed"] is True
    assert set(policy["version_exclusive_paths"]) == {
        ".github/workflows/v4-prediction.yml",
        ".github/workflows/v4-timing-probe.yml",
        ".github/workflows/fpl-engine-recovery.yml",
        ".github/workflows/v5-evidence-dispatcher.yml",
    }
    assert all("*" not in path for path in policy["version_exclusive_paths"])
    assert all(path.startswith(".github/workflows/") for path in policy["version_exclusive_paths"])
    assert all("/v3-" not in path for path in policy["version_exclusive_paths"])


def test_policy_rejects_security_flag_weakening(tmp_path):
    policy = provenance._load_policy().copy()
    policy["fail_closed_on_github_api_error"] = False
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(RuntimeError, match="MAIN_PROVENANCE_POLICY_INSECURE"):
        provenance._load_policy(path)


def test_policy_rejects_broad_version_scope(tmp_path):
    policy = provenance._load_policy().copy()
    policy["version_exclusive_paths"] = ["src/**"]
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(RuntimeError, match="MAIN_PROVENANCE_POLICY_VERSION_SCOPE_MUST_BE_EXACT"):
        provenance._load_policy(path)
