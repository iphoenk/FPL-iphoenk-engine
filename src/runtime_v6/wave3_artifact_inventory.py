"""Discover immutable Wave 3 artifacts from their producing workflow runs.

Never enumerate all repository artifacts: that unbounded GitHub CLI pagination
can exhaust the response decoder. The source run and per-run artifact endpoints
are GitHub-owned provenance. Downloaded proofs are still independently validated
by wave3_artifact_provenance before they can count toward natural acceptance.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

SOURCE_WORKFLOWS = {
    "prior": ("v6-wave3-proof.yml", "issues", 60),
    "chaos": ("v6-ci.yml", "push", 40),
}
ARTIFACT_PREFIXES = {
    "prior": "v6-wave3-slot-proof-",
    "chaos": "v6-wave3-chaos-acceptance-",
}
_SHA = re.compile(r"^[0-9a-f]{40}$")


class InventoryError(RuntimeError):
    """Do not silently turn missing or malformed provenance into a PASS."""


def github_api(path: str) -> dict[str, Any]:
    """Read a bounded GitHub REST response; retry truncated/transient reads."""
    last_error = ""
    for attempt in range(4):
        result = subprocess.run(
            ["gh", "api", path],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            try:
                response = json.loads(result.stdout)
                if isinstance(response, dict):
                    return response
                last_error = "GitHub response was not an object"
            except json.JSONDecodeError as exc:
                last_error = f"GitHub returned incomplete JSON: {exc}"
        else:
            last_error = (result.stderr or result.stdout).strip()[:400]
        if attempt < 3:
            time.sleep(2 ** attempt)
    raise InventoryError(f"GitHub artifact discovery failed closed for {path}: {last_error}")


def discover(
    kind: str,
    repository: str,
    *,
    current_run_id: int = 0,
    api: Callable[[str], dict[str, Any]] = github_api,
) -> list[str]:
    if kind not in SOURCE_WORKFLOWS:
        raise InventoryError(f"unsupported inventory kind: {kind}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise InventoryError("invalid GitHub repository identity")
    workflow, event, limit = SOURCE_WORKFLOWS[kind]
    endpoint = (
        f"/repos/{repository}/actions/workflows/{workflow}/runs"
        f"?event={event}&per_page={limit}"
    )
    run_rows = api(endpoint).get("workflow_runs")
    if not isinstance(run_rows, list):
        raise InventoryError("workflow run inventory is not a list")
    candidates: list[tuple[str, str]] = []
    required_path = f".github/workflows/{workflow}"
    for run in run_rows:
        if not isinstance(run, Mapping):
            raise InventoryError("malformed workflow run")
        try:
            run_id = int(run.get("id"))
        except (ValueError, TypeError) as exc:
            raise InventoryError("workflow run without numeric id") from exc
        if run_id == current_run_id or run.get("path") != required_path:
            continue
        if run.get("event") != event or run.get("conclusion") != "success":
            continue
        if run.get("status") != "completed":
            continue
        if kind == "chaos" and (
            run.get("name") != "FPL V6 CI contracts"
            or run.get("head_branch") != "main"
        ):
            continue
        sha = str(run.get("head_sha") or "").lower()
        if kind == "chaos" and not _SHA.fullmatch(sha):
            continue
        candidates.append((str(run_id), sha))

    rows: list[tuple[str, str, str]] = []
    seen_artifact_ids: set[int] = set()
    for run_id, sha in candidates:
        payload = api(f"/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100")
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            raise InventoryError(f"missing artifact list for workflow run {run_id}")
        for artifact in artifacts:
            if not isinstance(artifact, Mapping):
                raise InventoryError("malformed artifact row")
            name = str(artifact.get("name") or "")
            if not name.startswith(ARTIFACT_PREFIXES[kind]) or artifact.get("expired"):
                continue
            if "|" in name or "\n" in name:
                raise InventoryError("unsafe artifact name delimiter")
            provenance_run = artifact.get("workflow_run") or {}
            if str(provenance_run.get("id") or "") != run_id:
                raise InventoryError("artifact / producing workflow run mismatch")
            try:
                artifact_id = int(artifact["id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise InventoryError("invalid artifact id") from exc
            if artifact_id in seen_artifact_ids:
                raise InventoryError("duplicate artifact id in inventory")
            seen_artifact_ids.add(artifact_id)
            if kind == "prior":
                rows.append((str(artifact_id), name, run_id))
            else:
                rows.append((name, run_id, sha))
    # GitHub run and artifact listing order is normally newest-first; explicitly
    # preserve that server order without trusting names as proof of authenticity.
    return ["|".join(row) for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded Wave 3 artifact inventory")
    parser.add_argument("kind", choices=sorted(SOURCE_WORKFLOWS))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--current-run", type=int, default=0)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not os.environ.get("GH_TOKEN"):
        raise InventoryError("GH_TOKEN missing; cannot inspect provenance")
    rows = discover(args.kind, args.repo, current_run_id=args.current_run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(row + "\n" for row in rows), encoding="utf-8")
    print(json.dumps({"kind": args.kind, "index_rows": len(rows), "source": "WORKFLOW_RUN_SCOPED_GITHUB_API", "bounded": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
