from __future__ import annotations

import argparse
import json
import os

from src.runtime_v3.main_pr_provenance import _load_policy, verify_version_exclusive_main_advance


def run(source_commit: str, canonical_main: str) -> dict:
    policy = _load_policy()
    result = verify_version_exclusive_main_advance(
        api_url=os.environ.get("GITHUB_API_URL", ""),
        repository=os.environ.get("GITHUB_REPOSITORY", ""),
        source_sha=source_commit,
        head_sha=canonical_main,
        token=os.environ.get("GH_TOKEN", ""),
        version_exclusive_paths=set(policy["version_exclusive_paths"]),
        max_first_parent_commits=int(policy["max_first_parent_commits"]),
    )
    print(json.dumps(result, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--canonical-main", required=True)
    args = parser.parse_args()
    run(args.source_commit, args.canonical_main)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
