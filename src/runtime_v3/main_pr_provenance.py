from __future__ import annotations

import json
import os
from typing import Any
from urllib.request import Request, urlopen


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
    payload = _github_json(url, token)
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
        raise RuntimeError(
            f"REFUSING_DIRECT_MAIN_PUSH_WITHOUT_MERGED_PR source_commit={sha} branch={branch}"
        )

    chosen = sorted(merged, key=lambda pr: str(pr.get("merged_at") or ""), reverse=True)[0]
    return {
        "status": "PASS",
        "source_commit": sha,
        "branch": branch,
        "pull_request": chosen.get("number"),
        "merged_at": chosen.get("merged_at"),
    }


def run() -> dict[str, Any]:
    result = verify_main_commit_pr_provenance(
        api_url=os.environ.get("GITHUB_API_URL", ""),
        repository=os.environ.get("GITHUB_REPOSITORY", ""),
        sha=os.environ.get("GITHUB_SHA", ""),
        branch=os.environ.get("GITHUB_REF_NAME", ""),
        token=os.environ.get("GH_TOKEN", ""),
    )
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == "__main__":
    run()
