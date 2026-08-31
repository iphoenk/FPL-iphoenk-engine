from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.v5.canonical_provenance as provenance


def _policy() -> dict:
    return {
        "registry": "V5_CANONICAL_PROVENANCE_POLICY_V1",
        "schema_version": 1,
        "branch": "v5-unified-engine",
        "trust_anchor_sha": "a" * 40,
        "max_first_parent_commits": 16,
        "require_anchor_in_first_parent_history": True,
        "require_each_code_commit_after_anchor_from_merged_pr": True,
        "require_merge_commit_sha_match": True,
        "allow_governed_trigger_commits": True,
        "allowed_trigger_actor": "github-actions[bot]",
        "allowed_trigger_paths": ["config/v5_shadow_trigger.json", "config/v5_on_demand_trigger.json"],
        "allowed_trigger_message_prefixes": [
            "chore(v5): dispatch governed shadow evidence",
            "chore(v5): dispatch governed on-demand report",
        ],
        "require_verified_trigger_commit": True,
        "fail_closed_on_github_api_error": True,
    }


def _commit(
    sha: str,
    parent: str,
    *,
    actor: str = "iphoenk",
    message: str = "code",
    paths: list[str] | None = None,
    verified: bool = True,
) -> dict:
    return {
        "sha": sha,
        "author": {"login": actor},
        "parents": [{"sha": parent}],
        "commit": {"message": message, "verification": {"verified": verified}},
        "files": [{"filename": path} for path in (paths or ["src/v5/example.py"])],
    }


def test_policy_file_is_fail_closed_and_has_stable_anchor():
    payload = json.loads(Path("config/v5_canonical_provenance_registry.json").read_text(encoding="utf-8"))
    assert payload["branch"] == "v5-unified-engine"
    assert len(payload["trust_anchor_sha"]) == 40
    assert payload["require_each_code_commit_after_anchor_from_merged_pr"] is True
    assert payload["require_merge_commit_sha_match"] is True
    assert payload["allow_governed_trigger_commits"] is True
    assert payload["require_verified_trigger_commit"] is True
    assert payload["fail_closed_on_github_api_error"] is True


def test_history_accepts_merged_pr_then_governed_trigger_to_anchor(monkeypatch):
    policy = _policy()
    anchor = policy["trust_anchor_sha"]
    trigger = "b" * 40
    head = "c" * 40
    payloads = {
        f"commits/{head}/pulls": [
            {
                "number": 7,
                "state": "closed",
                "merged_at": "2026-08-31T00:00:00Z",
                "merge_commit_sha": head,
                "base": {"ref": "v5-unified-engine"},
            }
        ],
        f"commits/{head}": _commit(head, trigger),
        f"commits/{trigger}/pulls": [],
        f"commits/{trigger}": _commit(
            trigger,
            anchor,
            actor="github-actions[bot]",
            message="chore(v5): dispatch governed shadow evidence [TEST]",
            paths=["config/v5_shadow_trigger.json"],
        ),
    }

    def fake(url: str, _token: str):
        return next(value for key, value in payloads.items() if key in url)

    monkeypatch.setattr(provenance, "_github_json", fake)
    result = provenance.verify_canonical_history(
        api_url="https://api.github.test",
        repository="o/r",
        sha=head,
        branch="v5-unified-engine",
        token="t",
        policy=policy,
    )
    assert result["status"] == "PASS"
    assert [row["kind"] for row in result["verified_commits"]] == ["MERGED_PR", "GOVERNED_TRIGGER"]


def test_direct_code_push_is_rejected(monkeypatch):
    policy = _policy()
    head = "c" * 40
    anchor = policy["trust_anchor_sha"]
    payloads = {
        f"commits/{head}/pulls": [],
        f"commits/{head}": _commit(head, anchor, actor="iphoenk", paths=["src/v5/services/prediction.py"]),
    }

    def fake(url: str, _token: str):
        return next(value for key, value in payloads.items() if key in url)

    monkeypatch.setattr(provenance, "_github_json", fake)
    with pytest.raises(RuntimeError, match="REFUSING_UNPROVEN_V5_CANONICAL_COMMIT"):
        provenance.verify_canonical_history(
            api_url="https://api.github.test",
            repository="o/r",
            sha=head,
            branch="v5-unified-engine",
            token="t",
            policy=policy,
        )


def test_trigger_commit_cannot_smuggle_code(monkeypatch):
    policy = _policy()
    head = "b" * 40
    anchor = policy["trust_anchor_sha"]
    bad = _commit(
        head,
        anchor,
        actor="github-actions[bot]",
        message="chore(v5): dispatch governed shadow evidence",
        paths=["config/v5_shadow_trigger.json", "src/v5/services/prediction.py"],
    )
    payloads = {f"commits/{head}/pulls": [], f"commits/{head}": bad}

    def fake(url: str, _token: str):
        return next(value for key, value in payloads.items() if key in url)

    monkeypatch.setattr(provenance, "_github_json", fake)
    with pytest.raises(RuntimeError, match="REFUSING_UNPROVEN_V5_CANONICAL_COMMIT"):
        provenance.verify_canonical_history(
            api_url="https://api.github.test",
            repository="o/r",
            sha=head,
            branch="v5-unified-engine",
            token="t",
            policy=policy,
        )


def test_pr_association_must_match_merge_commit_sha(monkeypatch):
    policy = _policy()
    head = "c" * 40
    anchor = policy["trust_anchor_sha"]
    payloads = {
        f"commits/{head}/pulls": [
            {
                "number": 8,
                "state": "closed",
                "merged_at": "2026-08-31T00:00:00Z",
                "merge_commit_sha": "d" * 40,
                "base": {"ref": "v5-unified-engine"},
            }
        ],
        f"commits/{head}": _commit(head, anchor, actor="iphoenk", paths=["src/v5/services/prediction.py"]),
    }

    def fake(url: str, _token: str):
        return next(value for key, value in payloads.items() if key in url)

    monkeypatch.setattr(provenance, "_github_json", fake)
    with pytest.raises(RuntimeError, match="REFUSING_UNPROVEN_V5_CANONICAL_COMMIT"):
        provenance.verify_canonical_history(
            api_url="https://api.github.test",
            repository="o/r",
            sha=head,
            branch="v5-unified-engine",
            token="t",
            policy=policy,
        )


def test_canonical_workflows_enforce_provenance_before_operational_use():
    workflows = Path(".github/workflows")
    unified = (workflows / "v5-unified-gate.yml").read_text(encoding="utf-8")
    shadow = (workflows / "v5-shadow-cycle.yml").read_text(encoding="utf-8")
    ondemand = (workflows / "v5-on-demand-report.yml").read_text(encoding="utf-8")
    manual = (workflows / "v5-evidence-scheduler.yml").read_text(encoding="utf-8")
    dedicated = (workflows / "v5-canonical-provenance.yml").read_text(encoding="utf-8")
    for text in (unified, shadow, ondemand, manual, dedicated):
        assert "pull-requests: read" in text
        assert "src.v5.canonical_provenance" in text
    assert "refs/heads/v5-unified-engine" in unified
    assert "branches: [v5-unified-engine]" in dedicated
