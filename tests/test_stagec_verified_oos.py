"""Proof-based Stage C acceptance: two genuine Git histories, not a mock receipt."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from src.engines.v12_stagec_verified_oos import (
    StageCOOSReplayError, run_verified_stagec_oos,
)

OCC = "reports/2026-27/gw_7/20261016_102000_plus_0700"
SLOT = "2026-10-16T10:20:00+07:00"
CAPTURED = "2026-10-16T03:30:37Z"
DEADLINE = "2026-10-17T10:00:00Z"
KICKOFF = "2026-10-17T11:30:00Z"
SETTLED = "2026-10-18T12:00:00Z"
CHECKED = "2026-10-18T11:59:00Z"


def git(repo: Path, *args, when="2026-10-16T04:00:00+00:00"):
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], env=env, stderr=subprocess.DEVNULL,
    ).decode().strip()


def commit(repo, msg, when):
    git(repo, "add", ".")
    git(repo, "commit", "-qm", msg, when=when)
    return git(repo, "rev-parse", "HEAD")


def write(repo, path, payload):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def history(tmp_path, *, total=50, finished=True, receipt_valid=True, missing_outcome=False):
    private, runtime = tmp_path / "private", tmp_path / "runtime"
    for repo in (private, runtime):
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "CI")
        git(repo, "config", "user.email", "ci@example.com")

    rows = []
    outcomes = []
    for pid in range(1, total + 1):
        starter = pid % 2 == 0
        team_id = 1 if pid <= total // 2 else 2
        rows.append({
            "element": pid, "team_id": team_id,
            "baseline": {"start_probability": 0.5, "expected_minutes": 40},
            "individualized": {
                "start_probability": 0.9 if starter else 0.1,
                "expected_minutes": 85 if starter else 2,
            },
        })
        if missing_outcome and pid == total:
            continue
        outcomes.append({
            "official_element_id": pid, "team_id": team_id, "gw": 7,
            "official_fixture_id": 61, "identity_status": "EXACT",
            "fixture_identity_status": "EXACT", "source": "official_fpl",
            "dataset": "event_live", "starter": starter,
            "minutes": 88 if starter else 0,
            "source_checked_at": CHECKED, "kickoff_time": KICKOFF,
        })
    forecast = {
        "contract": "V12_PSTART_PROSPECTIVE_PREDEADLINE_V1",
        "captured_at": CAPTURED, "official_deadline": DEADLINE,
        "planning_gw": 7, "report_slot": SLOT,
        "model_sha": "a" * 40, "model_owner": "V12_PLAYER_MINUTES",
        "source": {"id": "official_fpl", "original_git_evidence": {
            "git_object_readback": "PASS",
        }},
        "universe_expected": total, "universe_observed": total,
        "forecast_rows": rows,
        "forecast_rows_sha256": hashlib.sha256(
            json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    write(private, OCC + "/pstart_predeadline_forecast.json", forecast)
    original = commit(private, "freeze original forecast", "2026-10-16T04:00:00+00:00")
    raw = (private / OCC / "pstart_predeadline_forecast.json").read_bytes()
    receipt = {
        "delivery_status": "READY_FULL",
        "private_remote_readback": "PASS" if receipt_valid else "FAIL",
        "pstart_prospective_remote_readback": "PASS",
        "pstart_prospective_source_sha256_readback": "PASS",
        "pstart_prospective_status": "IMMUTABLE_REMOTE_READBACK_VERIFIED",
        "pstart_prospective_private_commit": original,
        "pstart_prospective_sha256": hashlib.sha256(raw).hexdigest(),
        "model_sha": "a" * 40, "report_slot": SLOT, "planning_gw": 7,
    }
    write(private, OCC + "/delivery_receipt.json", receipt)
    latest = commit(private, "persist final receipt", "2026-10-16T04:05:00+00:00")
    normalized = {
        "source_id": "official_fpl", "effective_at": SETTLED,
        "history_coverage": {"finished_gws": [7] if finished else []},
        "record_groups": {"player_matches": outcomes},
    }
    fixtures = {
        "authority": "official_fpl",
        "fixtures": [{
            "event": 7, "official_fpl_fixture_id": 61, "team_h": 1,
            "team_a": 2, "identity_authority": "official_fpl",
            "finished": finished, "kickoff_time": KICKOFF,
        }],
    }
    write(runtime, "data/v6/normalized/sources/official_fpl.json", normalized)
    write(runtime, "data/v6/normalized/canonical_fixtures.json", fixtures)
    settled = commit(runtime, "settled original V6", "2026-10-18T12:05:00+00:00")
    return {
        "private_repo": private, "private_commit": latest,
        "occurrence_path": OCC, "v6_repo": runtime,
        "settled_v6_commit": settled, "expected_universe": total,
        "minimum_sample": 50,
    }


def test_actual_git_original_frozen_and_settled_readback(tmp_path):
    kwargs = history(tmp_path)
    out = run_verified_stagec_oos(**kwargs)
    assert out["scored_sample"] == 50
    assert out["verdict"] == "PASS_SHADOW"
    assert out["starter_brier"] < out["baseline_starter_brier"]
    assert out["xmins_mae"] < out["baseline_xmins_mae"]
    assert out["evidence_status"] == "IMMUTABLE_FROZEN_AND_SETTLED_V6_READBACK_PASS"
    assert not out["production_activation_allowed"]
    assert not out["future_data_retrofit"]


def test_unsettled_event_cannot_score(tmp_path):
    kwargs = history(tmp_path, finished=False)
    with pytest.raises(StageCOOSReplayError, match="TARGET_GW_NOT_SETTLED_IN_V6"):
        run_verified_stagec_oos(**kwargs)


def test_incomplete_final_player_rows_cannot_score(tmp_path):
    kwargs = history(tmp_path, missing_outcome=True)
    with pytest.raises(StageCOOSReplayError, match="SETTLED_UNIVERSE_OUTCOMES_MISSING_OR_FOREIGN"):
        run_verified_stagec_oos(**kwargs)


def test_receipt_must_be_verified_from_original_private_git(tmp_path):
    kwargs = history(tmp_path, receipt_valid=False)
    with pytest.raises(StageCOOSReplayError, match="IMMUTABLE_PROSPECTIVE_RECEIPT_UNVERIFIED"):
        run_verified_stagec_oos(**kwargs)


def test_original_private_forecast_mutation_rejected(tmp_path):
    kwargs = history(tmp_path)
    p = kwargs["private_repo"] / OCC / "pstart_predeadline_forecast.json"
    forecast = json.loads(p.read_text())
    forecast["forecast_rows"][0]["individualized"]["expected_minutes"] = 0
    write(kwargs["private_repo"], OCC + "/pstart_predeadline_forecast.json", forecast)
    kwargs["private_commit"] = commit(
        kwargs["private_repo"], "tamper after freeze", "2026-10-16T04:10:00+00:00",
    )
    with pytest.raises(StageCOOSReplayError, match="FROZEN_FORECAST_BYTES_CHANGED"):
        run_verified_stagec_oos(**kwargs)


def test_minimum_sample_cannot_be_weakened_for_production(tmp_path):
    kwargs = history(tmp_path)
    kwargs["minimum_sample"] = 1
    with pytest.raises(StageCOOSReplayError, match="UNIVERSE_OR_SAMPLE_POLICY_INVALID"):
        run_verified_stagec_oos(**kwargs)
