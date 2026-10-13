from __future__ import annotations

import pytest

from src.runtime_v6.wave3_artifact_inventory import InventoryError, discover


REPO = "iphoenk/FPL-iphoenk-engine"
SHA = "a" * 40


def run(run_id: int, *, kind: str, conclusion: str = "success") -> dict:
    workflow = "v6-wave3-proof.yml" if kind == "prior" else "v6-ci.yml"
    return {
        "id": run_id,
        "path": f".github/workflows/{workflow}",
        "event": "issues" if kind == "prior" else "push",
        "status": "completed",
        "conclusion": conclusion,
        "name": "FPL V6 Wave 3 natural proof" if kind == "prior" else "FPL V6 CI contracts",
        "head_branch": "main",
        "head_sha": SHA,
    }


def artifact(artifact_id: int, *, run_id: int, name: str) -> dict:
    return {
        "id": artifact_id,
        "name": name,
        "expired": False,
        "workflow_run": {"id": run_id},
    }


def test_prior_scoped_to_successful_issue_event_and_excludes_current():
    rows = [
        run(30, kind="prior"),
        run(29, kind="prior", conclusion="failure"),
        run(28, kind="prior"),
        run(27, kind="prior"),
    ]
    responses = {
        f"/repos/{REPO}/actions/workflows/v6-wave3-proof.yml/runs?event=issues&per_page=60":
            {"workflow_runs": rows},
        f"/repos/{REPO}/actions/runs/28/artifacts?per_page=100":
            {"artifacts": [artifact(201, run_id=28, name="v6-wave3-slot-proof-100-1")]},
        f"/repos/{REPO}/actions/runs/27/artifacts?per_page=100":
            {"artifacts": [artifact(200, run_id=27, name="v6-wave3-slot-proof-99-1")]},
    }
    paths = []

    def api(path):
        paths.append(path)
        return responses[path]

    result = discover("prior", REPO, current_run_id=30, api=api)
    assert result == [
        "201|v6-wave3-slot-proof-100-1|28",
        "200|v6-wave3-slot-proof-99-1|27",
    ]
    assert not any("/runs/30/artifacts" in path or "/runs/29/artifacts" in path for path in paths)
    assert all("/actions/artifacts" not in path for path in paths)


def test_chaos_scoped_to_successful_main_push():
    wrong_branch = run(7, kind="chaos")
    wrong_branch["head_branch"] = "experimental"
    responses = {
        f"/repos/{REPO}/actions/workflows/v6-ci.yml/runs?event=push&per_page=40":
            {"workflow_runs": [wrong_branch, run(6, kind="chaos")]},
        f"/repos/{REPO}/actions/runs/6/artifacts?per_page=100":
            {"artifacts": [artifact(88, run_id=6, name="v6-wave3-chaos-acceptance-6")]},
    }
    assert discover("chaos", REPO, api=responses.__getitem__) == [
        f"v6-wave3-chaos-acceptance-6|6|{SHA}"
    ]


def test_artifact_workflow_run_mismatch_fails_closed():
    responses = {
        f"/repos/{REPO}/actions/workflows/v6-wave3-proof.yml/runs?event=issues&per_page=60":
            {"workflow_runs": [run(4, kind="prior")]},
        f"/repos/{REPO}/actions/runs/4/artifacts?per_page=100":
            {"artifacts": [artifact(44, run_id=999, name="v6-wave3-slot-proof-2-1")]},
    }
    with pytest.raises(InventoryError, match="mismatch"):
        discover("prior", REPO, api=responses.__getitem__)


def test_missing_api_artifact_list_fails_closed():
    responses = {
        f"/repos/{REPO}/actions/workflows/v6-wave3-proof.yml/runs?event=issues&per_page=60":
            {"workflow_runs": [run(4, kind="prior")]},
        f"/repos/{REPO}/actions/runs/4/artifacts?per_page=100": {},
    }
    with pytest.raises(InventoryError, match="missing artifact list"):
        discover("prior", REPO, api=responses.__getitem__)


def test_no_candidates_is_empty_not_false_pass():
    responses = {
        f"/repos/{REPO}/actions/workflows/v6-wave3-proof.yml/runs?event=issues&per_page=60":
            {"workflow_runs": [run(4, kind="prior", conclusion="failure")]},
    }
    assert discover("prior", REPO, api=responses.__getitem__) == []
