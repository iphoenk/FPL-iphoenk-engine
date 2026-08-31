from __future__ import annotations

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


def _first_parent(commit: dict[str, Any]) -> str:
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
    metadata = commit.get("commit") if isinstance(commit.get("commit"), dict) else {}
    verification = metadata.get("verification") if isinstance(metadata.get("verification"), dict) else {}
    files = commit.get("files") if isinstance(commit.get("files"), list) else []
    paths = {
        str(row.get("filename"))
        for row in files
        if isinstance(row, dict) and row.get("filename")
    }
    allowed_paths = {str(value) for value in policy.get("allowed_trigger_paths") or []}
    prefixes = tuple(str(value) for value in policy.get("allowed_trigger_message_prefixes") or [])
    message = str(metadata.get("message") or "")
    return all(
        (
            author.get("login") == policy.get("allowed_trigger_actor"),
            policy.get("require_verified_trigger_commit") is not True or verification.get("verified") is True,
            bool(paths),
            paths.issubset(allowed_paths),
            bool(prefixes),
            message.startswith(prefixes),
            len(commit.get("parents") or []) == 1,
        )
    )


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
    paths = payload.get("allowed_trigger_paths")
    prefixes = payload.get("allowed_trigger_message_prefixes")
    if not isinstance(paths, list) or not paths or len(paths) != len(set(paths)):
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
        raise RuntimeError(
            f"V5_CANONICAL_PROVENANCE_BRANCH_MISMATCH runtime={branch} policy={policy.get('branch')}"
        )

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
        pr = _merged_pr(
            _github_json(pulls_url, token),
            branch=branch,
            sha=current,
            require_merge_sha=require_merge_sha,
        )
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
        elif policy.get("allow_governed_trigger_commits") is True and _governed_trigger(commit, policy):
            verified.append(
                {
                    "sha": current,
                    "kind": "GOVERNED_TRIGGER",
                    "paths": sorted(
                        str(row.get("filename"))
                        for row in commit.get("files") or []
                        if isinstance(row, dict) and row.get("filename")
                    ),
                }
            )
        else:
            raise RuntimeError(
                f"REFUSING_UNPROVEN_V5_CANONICAL_COMMIT source_commit={current} branch={branch}"
            )
        current = _first_parent(commit)

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
