"""Stage C/D post-settlement evaluation is shadow-only and fail-closed."""
import json
import subprocess
from pathlib import Path

import pytest

from src.engines import v12_stagec_postsettlement_replay as replay


def stub_git(monkeypatch, *, finished=True, receipt_good=True, valid_source=True):
    receipt = {
        "pstart_prospective_sha256": replay.ORIGINAL_FORECAST_SHA256 if receipt_good else "0" * 64,
        "pstart_prospective_remote_readback": "PASS",
        "private_remote_readback": "PASS",
        "pstart_prospective_private_commit": "a" * 40,
    }
    operations = []

    def fake_git(repo, *args):
        operations.append((str(repo), args))
        if args == ("rev-parse", "HEAD"):
            return ("b" * 40).encode()
        if args == ("show", "b" * 40 + ":" + replay.NORMALIZED_SOURCE):
            return json.dumps({
                "source_id": "official_fpl" if valid_source else "unknown",
                "history_coverage": {"finished_gws": [7] if finished else [1, 2, 3, 4, 5, 6]},
            }).encode()
        if args == ("show", "b" * 40 + ":" + replay.ORIGINAL_OCCURRENCE + "/delivery_receipt.json"):
            return json.dumps(receipt).encode()
        if args == ("cat-file", "-e", "a" * 40 + "^{commit}"):
            raise subprocess.CalledProcessError(1, "git")
        if args == ("fetch", "--no-tags", "--depth=1", "origin", "a" * 40):
            return b""
        raise AssertionError(f"unexpected git operation: {args}")

    monkeypatch.setattr(replay, "_git", fake_git)
    return operations


def fake_oos(**kwargs):
    return {
        "original_forecast_sha256": replay.ORIGINAL_FORECAST_SHA256,
        "scored_sample": 667,
        "evidence_status": "IMMUTABLE_FROZEN_AND_SETTLED_V6_READBACK_PASS",
        "verdict": "PASS_SHADOW",
        "starter_brier": 0.18,
        "baseline_starter_brier": 0.22,
        "xmins_mae": 16.1,
        "baseline_xmins_mae": 20.2,
        "settled_v6_normalized_sha256": "c" * 64,
    }


def call():
    return replay.evaluate_postsettlement(private_repo=Path("private"), v6_repo=Path("v6"))


def test_not_final_never_accesses_private_or_claims_activation(monkeypatch):
    calls = stub_git(monkeypatch, finished=False)
    result = call()
    assert result["status"] == "PENDING_SETTLEMENT"
    assert result["reason"] == "OFFICIAL_GW7_NOT_FINAL"
    assert not result["production_activation_allowed"]
    assert not result["numeric_parameters_mutated"]
    assert not any("private" in path for path, _ in calls)


def test_source_without_official_authority_is_blocked(monkeypatch):
    stub_git(monkeypatch, valid_source=False)
    assert call()["reason"] == "V6_SOURCE_NOT_AUTHORITATIVE"


def test_wrong_frozen_sha_fail_closed(monkeypatch):
    stub_git(monkeypatch, receipt_good=False)
    monkeypatch.setattr(replay, "run_verified_stagec_oos", lambda **kw: pytest.fail("must not replay"))
    assert call()["reason"] == "FROZEN_ANCHOR_MISMATCH"


def test_true_oos_pass_still_cannot_activate_context_model(monkeypatch):
    stub_git(monkeypatch)
    monkeypatch.setattr(replay, "run_verified_stagec_oos", fake_oos)
    result = call()
    assert result["status"] == "SHADOW_EVALUATED"
    assert result["reason"] == "BASELINE_BENCHMARK_PASS"
    assert result["calibrated_context_effect"] == "NOT_ESTABLISHED"
    assert result["stage_d_numeric_activation"] == "BLOCKED_UNCALIBRATED_CONTEXT_CHALLENGER"
    assert result["production_activation_allowed"] is False


def test_baseline_not_beaten_is_never_labelled_calibration_pass(monkeypatch):
    stub_git(monkeypatch)
    def worse(**kwargs):
        return {**fake_oos(**kwargs), "verdict": "INSUFFICIENT_OR_FAIL"}
    monkeypatch.setattr(replay, "run_verified_stagec_oos", worse)
    result = call()
    assert result["status"] == "SHADOW_EVALUATED"
    assert result["reason"] == "BASELINE_BENCHMARK_NOT_BEATEN"
    assert not result["production_activation_allowed"]


def test_missing_independently_verified_rows_blocks(monkeypatch):
    stub_git(monkeypatch)
    def partial(**kwargs):
        return {**fake_oos(**kwargs), "scored_sample": 666}
    monkeypatch.setattr(replay, "run_verified_stagec_oos", partial)
    assert call()["reason"] == "OOS_FROZEN_PROOF_INCOMPLETE"


def test_private_frozen_commit_is_fetched_explicitly_only_after_settlement(monkeypatch):
    calls = stub_git(monkeypatch)
    monkeypatch.setattr(replay, "run_verified_stagec_oos", fake_oos)
    result = replay.evaluate_postsettlement(
        private_repo=Path("private"), v6_repo=Path("v6"), fetch_original=True,
    )
    assert result["status"] == "SHADOW_EVALUATED"
    assert any(op[0] == "fetch" for _, op in calls)


def test_verifier_rejection_cannot_be_promoted(monkeypatch):
    stub_git(monkeypatch)
    def refuse(**kwargs):
        raise replay.StageCOOSReplayError("TARGET_GW_FIXTURE_UNFINISHED")
    monkeypatch.setattr(replay, "run_verified_stagec_oos", refuse)
    result = call()
    assert result["status"] == "BLOCKED"
    assert result["verifier_reason"] == "TARGET_GW_FIXTURE_UNFINISHED"
    assert not result["production_activation_allowed"]
