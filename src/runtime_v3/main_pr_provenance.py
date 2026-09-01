from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


POLICY_PATH = Path("config/runtime/main_provenance_policy.json")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED_TRUE_POLICY_FLAGS = (
    "require_anchor_in_first_parent_history",
    "require_each_first_parent_commit_after_anchor_from_merged_pr",
    "fail_closed_on_github_api_error",
    "version_exclusive_direct_commit_requires_all_changed_paths_allowed",
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


def _select_merged_pr(payload: Any, *, branch: str) -> dict[str, Any]:
    if not isinstance(payload, list):
        raise RuntimeError("MAIN_PR_PROVENANCE_INVALID_GITHUB_RESPONSE")

    merged = [
        pr
        for pr in payload
        if pr.get("merged_at")
        and (pr.get("base") or {}).get("ref") == branch
        and pr.get("state") == "closed"
    ]
    if not merged:
        raise RuntimeError("MAIN_PR_PROVENANCE_NO_MERGED_PR")
    return sorted(merged, key=lambda pr: str(pr.get("merged_at") or ""), reverse=True)[0]


def verify_main_commit_pr_provenance(
    *,
    api_url: str,
    repository: str,
    sha: str,
    branch: str,
    token: str,
) -> dict[str, Any]:
    if not api_url or not repository or not sha or not branch or not token:
        raise RuntimeError("MAIN_PR_PROVENANCE_MISSING_GITHUB_CONTEXT")

    url = f"{api_url.rstrip('/')}/repos/{repository}/commits/{sha}/pulls"
    try:
        chosen = _select_merged_pr(_github_json(url, token), branch=branch)
    except RuntimeError as exc:
        if str(exc) == "MAIN_PR_PROVENANCE_NO_MERGED_PR":
            raise RuntimeError(
                f"REFUSING_DIRECT_MAIN_PUSH_WITHOUT_MERGED_PR source_commit={sha} branch={branch}"
            ) from exc
        raise

    return {
        "status": "PASS",
        "source_commit": sha,
        "branch": branch,
        "pull_request": chosen.get("number"),
        "merged_at": chosen.get("merged_at"),
    }


def _fetch_commit_payload(*, api_url: str, repository: str, sha: str, token: str) -> dict[str, Any]:
    payload = _github_json(f"{api_url.rstrip('/')}/repos/{repository}/commits/{sha}", token)
    if not isinstance(payload, dict):
        raise RuntimeError("MAIN_PROVENANCE_INVALID_COMMIT_RESPONSE")
    return payload


def _first_parent(commit_payload: dict[str, Any], *, source_sha: str, anchor_sha: str) -> str:
    parents = commit_payload.get("parents")
    if not isinstance(parents, list) or not parents:
        raise RuntimeError(
            f"MAIN_PROVENANCE_TRUST_ANCHOR_NOT_REACHED source_commit={source_sha} anchor={anchor_sha}"
        )
    first_parent = parents[0]
    parent_sha = first_parent.get("sha") if isinstance(first_parent, dict) else None
    if not isinstance(parent_sha, str) or not parent_sha:
        raise RuntimeError("MAIN_PROVENANCE_INVALID_FIRST_PARENT")
    return parent_sha


def _changed_paths(commit_payload: dict[str, Any]) -> list[str]:
    files = commit_payload.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("MAIN_PROVENANCE_COMMIT_PATH_EVIDENCE_MISSING")
    paths: list[str] = []
    for row in files:
        path = row.get("filename") if isinstance(row, dict) else None
        if not isinstance(path, str) or not path:
            raise RuntimeError("MAIN_PROVENANCE_COMMIT_PATH_EVIDENCE_INVALID")
        paths.append(path)
    return sorted(set(paths))


def _version_exclusive_paths(commit_payload: dict[str, Any], allowed_paths: set[str]) -> list[str] | None:
    paths = _changed_paths(commit_payload)
    return paths if paths and set(paths).issubset(allowed_paths) else None


def verify_main_history_pr_provenance(
    *,
    api_url: str,
    repository: str,
    sha: str,
    branch: str,
    token: str,
    trust_anchor_sha: str,
    max_first_parent_commits: int = 256,
    allow_direct_version_exclusive_commits: bool = False,
    version_exclusive_paths: set[str] | None = None,
) -> dict[str, Any]:
    if not trust_anchor_sha:
        raise RuntimeError("MAIN_PROVENANCE_MISSING_TRUST_ANCHOR")
    if max_first_parent_commits < 1:
        raise RuntimeError("MAIN_PROVENANCE_INVALID_MAX_DEPTH")

    allowed_paths = set(version_exclusive_paths or set())
    current = sha
    verified: list[dict[str, Any]] = []
    commit_cache: dict[str, dict[str, Any]] = {}

    for _ in range(max_first_parent_commits + 1):
        if current == trust_anchor_sha:
            head = verified[0] if verified else None
            merged_rows = [row for row in verified if row.get("provenance") == "MERGED_PR"]
            direct_rows = [row for row in verified if row.get("provenance") == "VERSION_EXCLUSIVE_DIRECT"]
            return {
                "status": "PASS",
                "source_commit": sha,
                "branch": branch,
                "trust_anchor_sha": trust_anchor_sha,
                "history_enforcement": "FIRST_PARENT_TO_TRUST_ANCHOR",
                "commits_checked": len(verified),
                "first_parent_chain_integrity": True,
                "head_pull_request": head.get("pull_request") if head else None,
                "verified_commits": verified,
                "verified_pull_requests": merged_rows,
                "version_exclusive_direct_commits": direct_rows,
            }

        if current not in commit_cache:
            commit_cache[current] = _fetch_commit_payload(
                api_url=api_url,
                repository=repository,
                sha=current,
                token=token,
            )
        commit_payload = commit_cache[current]

        try:
            pr_result = verify_main_commit_pr_provenance(
                api_url=api_url,
                repository=repository,
                sha=current,
                branch=branch,
                token=token,
            )
            verified.append(
                {
                    "sha": current,
                    "provenance": "MERGED_PR",
                    "pull_request": pr_result.get("pull_request"),
                    "merged_at": pr_result.get("merged_at"),
                }
            )
        except RuntimeError as exc:
            if not str(exc).startswith("REFUSING_DIRECT_MAIN_PUSH_WITHOUT_MERGED_PR"):
                raise
            scoped_paths = None
            if allow_direct_version_exclusive_commits and allowed_paths:
                scoped_paths = _version_exclusive_paths(commit_payload, allowed_paths)
            if scoped_paths is None:
                raise RuntimeError(
                    f"MAIN_PROVENANCE_UNTRUSTED_ANCESTOR source_commit={current} branch={branch}"
                ) from exc
            verified.append(
                {
                    "sha": current,
                    "provenance": "VERSION_EXCLUSIVE_DIRECT",
                    "pull_request": None,
                    "merged_at": None,
                    "paths": scoped_paths,
                }
            )

        current = _first_parent(commit_payload, source_sha=sha, anchor_sha=trust_anchor_sha)

    raise RuntimeError(
        "MAIN_PROVENANCE_MAX_DEPTH_EXCEEDED "
        f"source_commit={sha} anchor={trust_anchor_sha} max={max_first_parent_commits}"
    )


def verify_version_exclusive_main_advance(
    *,
    api_url: str,
    repository: str,
    source_sha: str,
    head_sha: str,
    token: str,
    version_exclusive_paths: set[str],
    max_first_parent_commits: int = 256,
) -> dict[str, Any]:
    """Allow a V3 candidate to remain canonical across strictly version-exclusive main commits."""
    if not all((api_url, repository, source_sha, head_sha, token)):
        raise RuntimeError("V3_VERSION_SCOPE_MISSING_GITHUB_CONTEXT")
    if not _SHA40.fullmatch(source_sha) or not _SHA40.fullmatch(head_sha):
        raise RuntimeError("V3_VERSION_SCOPE_INVALID_SHA")
    if not version_exclusive_paths:
        raise RuntimeError("V3_VERSION_SCOPE_EMPTY_ALLOWLIST")
    if max_first_parent_commits < 1:
        raise RuntimeError("V3_VERSION_SCOPE_INVALID_MAX_DEPTH")

    current = head_sha
    verified: list[dict[str, Any]] = []
    for _ in range(max_first_parent_commits + 1):
        if current == source_sha:
            return {
                "status": "PASS",
                "source_commit": source_sha,
                "canonical_main": head_sha,
                "scope": "VERSION_EXCLUSIVE_MAIN_ADVANCE",
                "commits_checked": len(verified),
                "verified_commits": verified,
            }
        payload = _fetch_commit_payload(
            api_url=api_url,
            repository=repository,
            sha=current,
            token=token,
        )
        scoped_paths = _version_exclusive_paths(payload, set(version_exclusive_paths))
        if scoped_paths is None:
            raise RuntimeError(
                f"V3_VERSION_SCOPE_REFUSING_STALE_SOURCE source_commit={source_sha} canonical_main={head_sha} blocker={current}"
            )
        verified.append({"sha": current, "paths": scoped_paths})
        current = _first_parent(payload, source_sha=head_sha, anchor_sha=source_sha)

    raise RuntimeError(
        f"V3_VERSION_SCOPE_SOURCE_NOT_REACHED source_commit={source_sha} canonical_main={head_sha} max={max_first_parent_commits}"
    )


def _load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("MAIN_PROVENANCE_POLICY_UNREADABLE") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("MAIN_PROVENANCE_POLICY_INVALID")
    if payload.get("registry") != "V3_MAIN_PROVENANCE_POLICY_V1" or payload.get("schema_version") != 1:
        raise RuntimeError("MAIN_PROVENANCE_POLICY_REGISTRY_MISMATCH")
    if payload.get("branch") != "main":
        raise RuntimeError("MAIN_PROVENANCE_POLICY_BRANCH_INVALID")
    anchor = payload.get("trust_anchor_sha")
    if not isinstance(anchor, str) or not _SHA40.fullmatch(anchor):
        raise RuntimeError("MAIN_PROVENANCE_POLICY_ANCHOR_INVALID")
    max_depth = payload.get("max_first_parent_commits")
    if not isinstance(max_depth, int) or isinstance(max_depth, bool) or not 1 <= max_depth <= 4096:
        raise RuntimeError("MAIN_PROVENANCE_POLICY_MAX_DEPTH_INVALID")
    if any(payload.get(flag) is not True for flag in _REQUIRED_TRUE_POLICY_FLAGS):
        raise RuntimeError("MAIN_PROVENANCE_POLICY_INSECURE")

    allowed = payload.get("version_exclusive_paths")
    if not isinstance(allowed, list) or not allowed or any(not isinstance(path, str) or not path for path in allowed):
        raise RuntimeError("MAIN_PROVENANCE_POLICY_VERSION_SCOPE_INVALID")
    if len(set(allowed)) != len(allowed) or any("*" in path for path in allowed):
        raise RuntimeError("MAIN_PROVENANCE_POLICY_VERSION_SCOPE_MUST_BE_EXACT")
    if any(path.startswith("src/") or path.startswith("config/") or "/v3-" in path for path in allowed):
        raise RuntimeError("MAIN_PROVENANCE_POLICY_VERSION_SCOPE_TOO_BROAD")
    if payload.get("allow_direct_version_exclusive_commits") is not True:
        raise RuntimeError("MAIN_PROVENANCE_POLICY_VERSION_SCOPE_DISABLED")
    return payload


def run() -> dict[str, Any]:
    policy = _load_policy()
    branch = os.environ.get("GITHUB_REF_NAME", "")
    policy_branch = str(policy["branch"])
    if branch != policy_branch:
        raise RuntimeError(
            f"MAIN_PROVENANCE_BRANCH_POLICY_MISMATCH runtime={branch} policy={policy_branch}"
        )

    result = verify_main_history_pr_provenance(
        api_url=os.environ.get("GITHUB_API_URL", ""),
        repository=os.environ.get("GITHUB_REPOSITORY", ""),
        sha=os.environ.get("GITHUB_SHA", ""),
        branch=branch,
        token=os.environ.get("GH_TOKEN", ""),
        trust_anchor_sha=str(policy["trust_anchor_sha"]),
        max_first_parent_commits=int(policy["max_first_parent_commits"]),
        allow_direct_version_exclusive_commits=bool(policy["allow_direct_version_exclusive_commits"]),
        version_exclusive_paths=set(policy["version_exclusive_paths"]),
    )
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == "__main__":
    run()
