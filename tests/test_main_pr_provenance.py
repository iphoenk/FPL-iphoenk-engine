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
