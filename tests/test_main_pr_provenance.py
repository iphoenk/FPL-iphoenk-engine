import json

import pytest

from src.runtime_v3 import main_pr_provenance as provenance


def _pr(number: int, *, branch: str = "main", state: str = "closed", merged_at: str | None = "2026-08-31T07:00:00Z"):
    return {
        "number": number,
        "state": state,
        "merged_at": merged_at,
        "base": {"ref": branch},
    }


def test_accepts_merged_pr_targeting_current_branch(monkeypatch):
    monkeypatch.setattr(provenance, "_github_json", lambda url, token: [_pr(123)])
    result = provenance.verify_main_commit_pr_provenance(
        api_url="https://api.github.com",
        repository="iphoenk/FPL-iphoenk-engine",
        sha="abc123",
        branch="main",
        token="token",
    )
    assert result["status"] == "PASS"
    assert result["pull_request"] == 123


def test_rejects_direct_push_without_associated_merged_pr(monkeypatch):
    monkeypatch.setattr(provenance, "_github_json", lambda url, token: [])
    with pytest.raises(RuntimeError, match="REFUSING_DIRECT_MAIN_PUSH_WITHOUT_MERGED_PR"):
        provenance.verify_main_commit_pr_provenance(
            api_url="https://api.github.com",
            repository="iphoenk/FPL-iphoenk-engine",
            sha="abc123",
            branch="main",
            token="token",
        )


def test_rejects_open_or_wrong_base_pr(monkeypatch):
    monkeypatch.setattr(
        provenance,
        "_github_json",
        lambda url, token: [
            _pr(1, state="open", merged_at=None),
            _pr(2, branch="release"),
        ],
    )
    with pytest.raises(RuntimeError, match="REFUSING_DIRECT_MAIN_PUSH_WITHOUT_MERGED_PR"):
        provenance.verify_main_commit_pr_provenance(
            api_url="https://api.github.com",
            repository="iphoenk/FPL-iphoenk-engine",
            sha="abc123",
            branch="main",
            token="token",
        )


def test_missing_github_context_fails_closed():
    with pytest.raises(RuntimeError, match="MAIN_PR_PROVENANCE_MISSING_GITHUB_CONTEXT"):
        provenance.verify_main_commit_pr_provenance(
            api_url="",
            repository="iphoenk/FPL-iphoenk-engine",
            sha="abc123",
            branch="main",
            token="token",
        )


def test_history_accepts_only_merged_pr_commits_until_trust_anchor(monkeypatch):
    def fake_github(url, token):
        if url.endswith("/commits/head/pulls"):
            return [_pr(302, merged_at="2026-08-31T09:10:00Z")]
        if url.endswith("/commits/head"):
            return {"parents": [{"sha": "mid"}]}
        if url.endswith("/commits/mid/pulls"):
            return [_pr(301, merged_at="2026-08-31T09:00:00Z")]
        if url.endswith("/commits/mid"):
            return {"parents": [{"sha": "anchor"}]}
        raise AssertionError(url)

    monkeypatch.setattr(provenance, "_github_json", fake_github)
    result = provenance.verify_main_history_pr_provenance(
        api_url="https://api.github.com",
        repository="iphoenk/FPL-iphoenk-engine",
        sha="head",
        branch="main",
        token="token",
        trust_anchor_sha="anchor",
    )
    assert result["status"] == "PASS"
    assert result["commits_checked"] == 2
    assert result["first_parent_chain_integrity"] is True
    assert result["head_pull_request"] == 302
    assert [item["sha"] for item in result["verified_pull_requests"]] == ["head", "mid"]


def test_history_rejects_direct_commit_hidden_below_valid_head_pr(monkeypatch):
    def fake_github(url, token):
        if url.endswith("/commits/head/pulls"):
            return [_pr(302)]
        if url.endswith("/commits/head"):
            return {"parents": [{"sha": "rogue"}]}
        if url.endswith("/commits/rogue/pulls"):
            return []
        raise AssertionError(url)

    monkeypatch.setattr(provenance, "_github_json", fake_github)
    with pytest.raises(RuntimeError, match="MAIN_PROVENANCE_UNTRUSTED_ANCESTOR source_commit=rogue"):
        provenance.verify_main_history_pr_provenance(
            api_url="https://api.github.com",
            repository="iphoenk/FPL-iphoenk-engine",
            sha="head",
            branch="main",
            token="token",
            trust_anchor_sha="anchor",
        )


def test_history_rejects_rewritten_history_that_drops_trust_anchor(monkeypatch):
    def fake_github(url, token):
        if url.endswith("/commits/head/pulls"):
            return [_pr(302)]
        if url.endswith("/commits/head"):
            return {"parents": []}
        raise AssertionError(url)

    monkeypatch.setattr(provenance, "_github_json", fake_github)
    with pytest.raises(RuntimeError, match="MAIN_PROVENANCE_TRUST_ANCHOR_NOT_REACHED"):
        provenance.verify_main_history_pr_provenance(
            api_url="https://api.github.com",
            repository="iphoenk/FPL-iphoenk-engine",
            sha="head",
            branch="main",
            token="token",
            trust_anchor_sha="anchor",
        )


def test_history_fails_closed_on_invalid_commit_response(monkeypatch):
    def fake_github(url, token):
        if url.endswith("/commits/head/pulls"):
            return [_pr(302)]
        if url.endswith("/commits/head"):
            return []
        raise AssertionError(url)

    monkeypatch.setattr(provenance, "_github_json", fake_github)
    with pytest.raises(RuntimeError, match="MAIN_PROVENANCE_INVALID_COMMIT_RESPONSE"):
        provenance.verify_main_history_pr_provenance(
            api_url="https://api.github.com",
            repository="iphoenk/FPL-iphoenk-engine",
            sha="head",
            branch="main",
            token="token",
            trust_anchor_sha="anchor",
        )


def test_policy_is_registry_owned_and_points_to_current_proven_green_anchor():
    policy = provenance._load_policy()
    assert policy["registry"] == "V3_MAIN_PROVENANCE_POLICY_V1"
    assert policy["branch"] == "main"
    assert policy["trust_anchor_sha"] == "d025201abfb4c72bc707956275e77900f05dd87d"
    assert policy["require_anchor_in_first_parent_history"] is True
    assert policy["require_each_first_parent_commit_after_anchor_from_merged_pr"] is True
    assert policy["fail_closed_on_github_api_error"] is True


def test_policy_rejects_security_flag_weakening(tmp_path):
    policy = provenance._load_policy().copy()
    policy["fail_closed_on_github_api_error"] = False
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(RuntimeError, match="MAIN_PROVENANCE_POLICY_INSECURE"):
        provenance._load_policy(path)
