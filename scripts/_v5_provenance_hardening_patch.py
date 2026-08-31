from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one patch target in {path}, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def write_policy() -> None:
    payload = {
        "registry": "V5_CANONICAL_PROVENANCE_POLICY_V1",
        "schema_version": 1,
        "branch": "v5-unified-engine",
        "trust_anchor_sha": "14ca0166210576f34eee7da11d7b90d6792ef47a",
        "max_first_parent_commits": 256,
        "require_anchor_in_first_parent_history": True,
        "require_each_code_commit_after_anchor_from_merged_pr": True,
        "require_merge_commit_sha_match": True,
        "allow_governed_trigger_commits": True,
        "allowed_trigger_actor": "github-actions[bot]",
        "allowed_trigger_paths": [
            "config/v5_shadow_trigger.json",
            "config/v5_on_demand_trigger.json",
        ],
        "allowed_trigger_message_prefixes": [
            "chore(v5): dispatch governed shadow evidence",
            "chore(v5): dispatch governed on-demand report",
        ],
        "require_verified_trigger_commit": True,
        "fail_closed_on_github_api_error": True,
    }
    path = ROOT / "config/v5_canonical_provenance_registry.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_module() -> None:
    path = ROOT / "src/v5/canonical_provenance.py"
    path.write_text(r'''from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


POLICY_PATH = Path("config/v5_canonical_provenance_registry.json")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED_TRUE_FLAGS = (
    "require_anchor_in_first_parent_history",
    "require_each_code_commit_after_anchor_from_merged_pr",
    "require_merge_commit_sha_match",
    "allow_governed_trigger_commits",
    "require_verified_trigger_commit",
    "fail_closed_on_github_api_error",
)


def _github_json(url: str, token: str) -> Any:
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _merged_pr(payload: Any, *, branch: str, sha: str, require_merge_sha: bool) -> dict[str, Any] | None:
    if not isinstance(payload, list):
        raise RuntimeError("V5_CANONICAL_PROVENANCE_INVALID_PR_RESPONSE")
    rows = [
        pr
        for pr in payload
        if pr.get("merged_at")
        and pr.get("state") == "closed"
        and (pr.get("base") or {}).get("ref") == branch
        and (not require_merge_sha or str(pr.get("merge_commit_sha") or "") == sha)
    ]
    if not rows:
        return None
    return sorted(rows, key=lambda pr: str(pr.get("merged_at") or ""), reverse=True)[0]


def _commit_parent(commit: dict[str, Any]) -> str:
    parents = commit.get("parents")
    if not isinstance(parents, list) or not parents:
        raise RuntimeError("V5_CANONICAL_PROVENANCE_PARENT_MISSING")
    first = parents[0]
    parent = first.get("sha") if isinstance(first, dict) else None
    if not isinstance(parent, str) or not _SHA40.fullmatch(parent):
        raise RuntimeError("V5_CANONICAL_PROVENANCE_PARENT_INVALID")
    return parent


def _governed_trigger(commit: dict[str, Any], policy: dict[str, Any]) -> bool:
    author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
    commit_meta = commit.get("commit") if isinstance(commit.get("commit"), dict) else {}
    verification = commit_meta.get("verification") if isinstance(commit_meta.get("verification"), dict) else {}
    files = commit.get("files") if isinstance(commit.get("files"), list) else []
    paths = {
        str(row.get("filename"))
        for row in files
        if isinstance(row, dict) and row.get("filename")
    }
    allowed_paths = {str(value) for value in policy.get("allowed_trigger_paths") or []}
    prefixes = tuple(str(value) for value in policy.get("allowed_trigger_message_prefixes") or [])
    message = str(commit_meta.get("message") or "")
    if author.get("login") != policy.get("allowed_trigger_actor"):
        return False
    if policy.get("require_verified_trigger_commit") is True and verification.get("verified") is not True:
        return False
    if not paths or not paths.issubset(allowed_paths):
        return False
    if not prefixes or not message.startswith(prefixes):
        return False
    if len(commit.get("parents") or []) != 1:
        return False
    return True


def _load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("V5_CANONICAL_PROVENANCE_POLICY_UNREADABLE") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("V5_CANONICAL_PROVENANCE_POLICY_INVALID")
    if payload.get("registry") != "V5_CANONICAL_PROVENANCE_POLICY_V1" or payload.get("schema_version") != 1:
        raise RuntimeError("V5_CANONICAL_PROVENANCE_POLICY_REGISTRY_MISMATCH")
    if payload.get("branch") != "v5-unified-engine":
        raise RuntimeError("V5_CANONICAL_PROVENANCE_POLICY_BRANCH_INVALID")
    anchor = payload.get("trust_anchor_sha")
    if not isinstance(anchor, str) or not _SHA40.fullmatch(anchor):
        raise RuntimeError("V5_CANONICAL_PROVENANCE_POLICY_ANCHOR_INVALID")
    max_depth = payload.get("max_first_parent_commits")
    if not isinstance(max_depth, int) or isinstance(max_depth, bool) or not 1 <= max_depth <= 4096:
        raise RuntimeError("V5_CANONICAL_PROVENANCE_POLICY_MAX_DEPTH_INVALID")
    if any(payload.get(flag) is not True for flag in _REQUIRED_TRUE_FLAGS):
        raise RuntimeError("V5_CANONICAL_PROVENANCE_POLICY_INSECURE")
    allowed_paths = payload.get("allowed_trigger_paths")
    prefixes = payload.get("allowed_trigger_message_prefixes")
    if not isinstance(allowed_paths, list) or not allowed_paths or len(allowed_paths) != len(set(allowed_paths)):
        raise RuntimeError("V5_CANONICAL_PROVENANCE_POLICY_TRIGGER_PATHS_INVALID")
    if not isinstance(prefixes, list) or not prefixes or len(prefixes) != len(set(prefixes)):
        raise RuntimeError("V5_CANONICAL_PROVENANCE_POLICY_TRIGGER_PREFIXES_INVALID")
    if not isinstance(payload.get("allowed_trigger_actor"), str) or not payload.get("allowed_trigger_actor"):
        raise RuntimeError("V5_CANONICAL_PROVENANCE_POLICY_TRIGGER_ACTOR_INVALID")
    return payload


def verify_canonical_history(
    *,
    api_url: str,
    repository: str,
    sha: str,
    branch: str,
    token: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    if not api_url or not repository or not token:
        raise RuntimeError("V5_CANONICAL_PROVENANCE_MISSING_GITHUB_CONTEXT")
    if not _SHA40.fullmatch(sha):
        raise RuntimeError("V5_CANONICAL_PROVENANCE_SHA_INVALID")
    if branch != policy.get("branch"):
        raise RuntimeError(f"V5_CANONICAL_PROVENANCE_BRANCH_MISMATCH runtime={branch} policy={policy.get('branch')}")

    anchor = str(policy["trust_anchor_sha"])
    max_depth = int(policy["max_first_parent_commits"])
    require_merge_sha = policy.get("require_merge_commit_sha_match") is True
    current = sha
    verified: list[dict[str, Any]] = []

    for _ in range(max_depth + 1):
        if current == anchor:
            return {
                "status": "PASS",
                "source_commit": sha,
                "branch": branch,
                "trust_anchor_sha": anchor,
                "history_enforcement": "FIRST_PARENT_TO_TRUST_ANCHOR",
                "commits_checked": len(verified),
                "first_parent_chain_integrity": True,
                "verified_commits": verified,
            }

        pulls_url = f"{api_url.rstrip('/')}/repos/{repository}/commits/{current}/pulls"
        pr = _merged_pr(_github_json(pulls_url, token), branch=branch, sha=current, require_merge_sha=require_merge_sha)
        commit_url = f"{api_url.rstrip('/')}/repos/{repository}/commits/{current}"
        commit = _github_json(commit_url, token)
        if not isinstance(commit, dict):
            raise RuntimeError("V5_CANONICAL_PROVENANCE_INVALID_COMMIT_RESPONSE")

        if pr is not None:
            verified.append(
                {
                    "sha": current,
                    "kind": "MERGED_PR",
                    "pull_request": pr.get("number"),
                    "merged_at": pr.get("merged_at"),
                }
            )
        elif _governed_trigger(commit, policy):
            verified.append(
                {
                    "sha": current,
                    "kind": "GOVERNED_TRIGGER",
                    "paths": sorted(str(row.get("filename")) for row in commit.get("files") or [] if isinstance(row, dict)),
                }
            )
        else:
            raise RuntimeError(
                f"REFUSING_UNPROVEN_V5_CANONICAL_COMMIT source_commit={current} branch={branch}"
            )
        current = _commit_parent(commit)

    raise RuntimeError(
        f"V5_CANONICAL_PROVENANCE_MAX_DEPTH_EXCEEDED source_commit={sha} anchor={anchor} max={max_depth}"
    )


def run() -> dict[str, Any]:
    policy = _load_policy()
    branch = os.environ.get("V5_PROVENANCE_BRANCH") or os.environ.get("GITHUB_REF_NAME", "")
    sha = os.environ.get("V5_PROVENANCE_SHA") or os.environ.get("GITHUB_SHA", "")
    result = verify_canonical_history(
        api_url=os.environ.get("GITHUB_API_URL", ""),
        repository=os.environ.get("GITHUB_REPOSITORY", ""),
        sha=sha,
        branch=branch,
        token=os.environ.get("GH_TOKEN", ""),
        policy=policy,
    )
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == "__main__":
    run()
''', encoding="utf-8")


def write_tests() -> None:
    path = ROOT / "tests/test_v5_canonical_provenance.py"
    path.write_text(r'''from __future__ import annotations

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
        "allowed_trigger_message_prefixes": ["chore(v5): dispatch governed shadow evidence", "chore(v5): dispatch governed on-demand report"],
        "require_verified_trigger_commit": True,
        "fail_closed_on_github_api_error": True,
    }


def _commit(sha: str, parent: str, *, actor: str = "iphoenk", message: str = "code", paths: list[str] | None = None, verified: bool = True) -> dict:
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
        f"commits/{head}/pulls": [{"number": 7, "state": "closed", "merged_at": "2026-08-31T00:00:00Z", "merge_commit_sha": head, "base": {"ref": "v5-unified-engine"}}],
        f"commits/{head}": _commit(head, trigger),
        f"commits/{trigger}/pulls": [],
        f"commits/{trigger}": _commit(trigger, anchor, actor="github-actions[bot]", message="chore(v5): dispatch governed shadow evidence [TEST]", paths=["config/v5_shadow_trigger.json"]),
    }

    def fake(url: str, _token: str):
        return next(value for key, value in payloads.items() if key in url)

    monkeypatch.setattr(provenance, "_github_json", fake)
    result = provenance.verify_canonical_history(api_url="https://api.github.test", repository="o/r", sha=head, branch="v5-unified-engine", token="t", policy=policy)
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
        provenance.verify_canonical_history(api_url="https://api.github.test", repository="o/r", sha=head, branch="v5-unified-engine", token="t", policy=policy)


def test_trigger_commit_requires_bot_verified_and_trigger_only(monkeypatch):
    policy = _policy()
    head = "b" * 40
    anchor = policy["trust_anchor_sha"]
    bad = _commit(head, anchor, actor="github-actions[bot]", message="chore(v5): dispatch governed shadow evidence", paths=["config/v5_shadow_trigger.json", "src/v5/services/prediction.py"])
    payloads = {f"commits/{head}/pulls": [], f"commits/{head}": bad}

    def fake(url: str, _token: str):
        return next(value for key, value in payloads.items() if key in url)

    monkeypatch.setattr(provenance, "_github_json", fake)
    with pytest.raises(RuntimeError, match="REFUSING_UNPROVEN_V5_CANONICAL_COMMIT"):
        provenance.verify_canonical_history(api_url="https://api.github.test", repository="o/r", sha=head, branch="v5-unified-engine", token="t", policy=policy)


def test_pr_association_must_match_merge_commit_sha(monkeypatch):
    policy = _policy()
    head = "c" * 40
    anchor = policy["trust_anchor_sha"]
    payloads = {
        f"commits/{head}/pulls": [{"number": 8, "state": "closed", "merged_at": "2026-08-31T00:00:00Z", "merge_commit_sha": "d" * 40, "base": {"ref": "v5-unified-engine"}}],
        f"commits/{head}": _commit(head, anchor, actor="iphoenk", paths=["src/v5/services/prediction.py"]),
    }

    def fake(url: str, _token: str):
        return next(value for key, value in payloads.items() if key in url)

    monkeypatch.setattr(provenance, "_github_json", fake)
    with pytest.raises(RuntimeError, match="REFUSING_UNPROVEN_V5_CANONICAL_COMMIT"):
        provenance.verify_canonical_history(api_url="https://api.github.test", repository="o/r", sha=head, branch="v5-unified-engine", token="t", policy=policy)


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
''', encoding="utf-8")


def write_dedicated_workflow() -> None:
    path = ROOT / ".github/workflows/v5-canonical-provenance.yml"
    path.write_text('''name: V5 Canonical Provenance\n\non:\n  push:\n    branches: [v5-unified-engine]\n\npermissions:\n  contents: read\n  pull-requests: read\n\nconcurrency:\n  group: v5-canonical-provenance\n  cancel-in-progress: false\n\njobs:\n  provenance:\n    runs-on: ubuntu-latest\n    timeout-minutes: 5\n    steps:\n      - name: Checkout canonical V5\n        uses: actions/checkout@v4\n        with:\n          fetch-depth: 1\n          persist-credentials: false\n      - name: Set up Python\n        uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n      - name: Enforce first-parent merged-PR provenance\n        env:\n          GH_TOKEN: ${{ github.token }}\n        run: python -m src.v5.canonical_provenance\n''', encoding="utf-8")


def patch_workflows() -> None:
    replace_once(
        ".github/workflows/v5-unified-gate.yml",
        "permissions: {contents: read}\n",
        "permissions:\n  contents: read\n  pull-requests: read\n",
    )
    replace_once(
        ".github/workflows/v5-unified-gate.yml",
        "      - name: Set up Python\n",
        "      - name: Enforce V5 canonical merged-PR provenance\n        if: github.event_name == 'push' && github.ref == 'refs/heads/v5-unified-engine'\n        env:\n          GH_TOKEN: ${{ github.token }}\n        run: python -m src.v5.canonical_provenance\n      - name: Set up Python\n",
    )

    for path in (".github/workflows/v5-shadow-cycle.yml", ".github/workflows/v5-on-demand-report.yml"):
        replace_once(path, "permissions:\n  contents: write\n", "permissions:\n  contents: write\n  pull-requests: read\n")
        replace_once(
            path,
            "      - name: Install dependencies\n",
            "      - name: Enforce V5 canonical provenance\n        env:\n          GH_TOKEN: ${{ github.token }}\n        run: python -m src.v5.canonical_provenance\n\n      - name: Install dependencies\n",
        )

    replace_once(
        ".github/workflows/v5-evidence-scheduler.yml",
        "permissions:\n  contents: write\n",
        "permissions:\n  contents: write\n  pull-requests: read\n",
    )
    replace_once(
        ".github/workflows/v5-evidence-scheduler.yml",
        "      - name: Evaluate governed evidence window\n",
        "      - name: Enforce V5 canonical provenance\n        env:\n          GH_TOKEN: ${{ github.token }}\n          V5_PROVENANCE_BRANCH: v5-unified-engine\n        run: V5_PROVENANCE_SHA=\"$(git rev-parse HEAD)\" python -m src.v5.canonical_provenance\n\n      - name: Evaluate governed evidence window\n",
    )


def patch_catalog_and_fingerprint() -> None:
    catalog = ROOT / "config/v5_registry_catalog.json"
    text = catalog.read_text(encoding="utf-8")
    if '"canonical_provenance"' in text:
        raise RuntimeError("canonical provenance catalog entry already exists")
    if '"version": 4' not in text:
        raise RuntimeError("registry catalog version drift before provenance patch")
    text = text.replace('"version": 4', '"version": 5', 1)
    marker = '    "architecture_principles": {"authority": "config/v5_architecture_principles.json", "status": "ACTIVE"},\n'
    if text.count(marker) != 1:
        raise RuntimeError("registry catalog architecture marker drift")
    text = text.replace(marker, marker + '    "canonical_provenance": {"authority": "config/v5_canonical_provenance_registry.json", "runtime_enforcer": "src/v5/canonical_provenance.py", "status": "ACTIVE"},\n', 1)
    catalog.write_text(text, encoding="utf-8")

    path = ROOT / "config/v5_release_integrity_registry.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    files = payload.get("include_files")
    if not isinstance(files, list):
        raise RuntimeError("release integrity include_files invalid")
    for item in ("config/v5_prediction_service_registry.json", "config/v5_canonical_provenance_registry.json"):
        if item not in files:
            files.append(item)
    payload["version"] = max(int(payload.get("version") or 0), 3)
    payload["contract"] = "V5_RUNTIME_RELEASE_FINGERPRINT_V3"
    payload.setdefault("governance", {})["runtime_authority_registries_are_fingerprinted"] = True
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    write_policy()
    write_module()
    write_tests()
    write_dedicated_workflow()
    patch_workflows()
    patch_catalog_and_fingerprint()
    print("V5 canonical provenance hardening patch applied")


if __name__ == "__main__":
    main()
