"""Post-settlement GW7 Stage C shadow replay on the EXISTING V12 DEEP runner.

This is an aggregate, read-only checkpoint, NOT a numeric model activation.
There is intentionally no new schedule, workflow or P(start) owner here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from src.engines.v12_stagec_verified_oos import (
    StageCOOSReplayError,
    run_verified_stagec_oos,
)

# Independently pinned, previously published PRIVATE immutable GW7 forecast.
# Do not use a movable latest pointer or regenerate its predeadline predictions.
TARGET_GW = 7
OFFICIAL_UNIVERSE = 667
ORIGINAL_OCCURRENCE = "reports/2026-27/gw_7/20261016_132900_plus_0700"
ORIGINAL_FORECAST_SHA256 = (
    "b4a1457a2ce8ec014201eae5ad53a8cc0768dc78847d8b868f23b342249cbec9"
)
NORMALIZED_SOURCE = "data/v6/normalized/sources/official_fpl.json"


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL
    )


def _summary(status: str, reason: str, **metrics: Any) -> dict[str, Any]:
    return {
        "contract": "V12_STAGECD_POSTSETTLEMENT_REPLAY_V1",
        "status": status,
        "reason": reason,
        "planning_gw": TARGET_GW,
        "official_universe_expected": OFFICIAL_UNIVERSE,
        "source": "ORIGINAL_GIT_OBJECTS_ONLY",
        "evaluation": "SHADOW_ONLY",
        "stage_d_numeric_activation": "BLOCKED_UNCALIBRATED_CONTEXT_CHALLENGER",
        "production_activation_allowed": False,
        "numeric_parameters_mutated": False,
        "new_scheduler": False,
        **metrics,
    }


def evaluate_postsettlement(
    *,
    private_repo: Path,
    v6_repo: Path,
    fetch_original: bool = False,
) -> dict[str, Any]:
    """Require FINAL V6 source before accessing the frozen private forecast.

    A passing comparison of EXISTING individualized vs baseline is not evidence
    that a new coach/role/medical challenger has been validated or may be active.
    """
    try:
        v6_sha = _git(v6_repo, "rev-parse", "HEAD").decode().strip()
        raw = _git(v6_repo, "show", f"{v6_sha}:{NORMALIZED_SOURCE}")
        normalized = json.loads(raw)
        if not isinstance(normalized, dict) or normalized.get("source_id") != "official_fpl":
            return _summary("BLOCKED", "V6_SOURCE_NOT_AUTHORITATIVE")
        finished = (normalized.get("history_coverage") or {}).get("finished_gws") or []
        if TARGET_GW not in finished:
            return _summary("PENDING_SETTLEMENT", "OFFICIAL_GW7_NOT_FINAL")
        private_sha = _git(private_repo, "rev-parse", "HEAD").decode().strip()
        receipt_raw = _git(private_repo, "show", f"{private_sha}:{ORIGINAL_OCCURRENCE}/delivery_receipt.json")
        receipt = json.loads(receipt_raw)
        if not isinstance(receipt, dict):
            return _summary("BLOCKED", "ORIGINAL_RECEIPT_INVALID")
        if (
            receipt.get("pstart_prospective_sha256") != ORIGINAL_FORECAST_SHA256
            or receipt.get("pstart_prospective_remote_readback") != "PASS"
            or receipt.get("private_remote_readback") != "PASS"
        ):
            return _summary("BLOCKED", "FROZEN_ANCHOR_MISMATCH")
        frozen_commit = receipt.get("pstart_prospective_private_commit")
        if not isinstance(frozen_commit, str) or len(frozen_commit) != 40 or not all(
            ch in "0123456789abcdef" for ch in frozen_commit
        ):
            return _summary("BLOCKED", "ORIGINAL_COMMIT_INVALID")
        if fetch_original:
            try:
                _git(private_repo, "cat-file", "-e", frozen_commit + "^{commit}")
            except subprocess.CalledProcessError:
                # Explicit one-off Git object fetch, not a scheduled acquisition.
                # The immutable target commit is taken only from the checked
                # ORIGINAL receipt, never a user-provided PR/body field.
                _git(private_repo, "fetch", "--no-tags", "--depth=1", "origin", frozen_commit)
        result = run_verified_stagec_oos(
            private_repo=private_repo,
            private_commit=private_sha,
            occurrence_path=ORIGINAL_OCCURRENCE,
            v6_repo=v6_repo,
            settled_v6_commit=v6_sha,
            expected_universe=OFFICIAL_UNIVERSE,
            minimum_sample=50,
        )
        if (
            result.get("original_forecast_sha256") != ORIGINAL_FORECAST_SHA256
            or result.get("scored_sample") != OFFICIAL_UNIVERSE
            or result.get("evidence_status") != "IMMUTABLE_FROZEN_AND_SETTLED_V6_READBACK_PASS"
        ):
            return _summary("BLOCKED", "OOS_FROZEN_PROOF_INCOMPLETE")
        # The paired predictions are existing baseline and individualized
        # canonical outputs. Never call this coach/role/availability calibration.
        outcome = "BASELINE_BENCHMARK_PASS" if result.get("verdict") == "PASS_SHADOW" else "BASELINE_BENCHMARK_NOT_BEATEN"
        return _summary(
            "SHADOW_EVALUATED",
            outcome,
            sample_size=result["scored_sample"],
            starter_brier=result["starter_brier"],
            baseline_starter_brier=result["baseline_starter_brier"],
            xmins_mae=result["xmins_mae"],
            baseline_xmins_mae=result["baseline_xmins_mae"],
            calibrated_context_effect="NOT_ESTABLISHED",
            historical_outcome_original_sha256=result["settled_v6_normalized_sha256"],
            frozen_original_sha256=ORIGINAL_FORECAST_SHA256,
        )
    except StageCOOSReplayError as exc:
        # The verifier exposes allowlisted machine reasons only.
        return _summary("BLOCKED", "VERIFIED_REPLAY_REJECTED", verifier_reason=str(exc))
    except (OSError, subprocess.CalledProcessError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return _summary("BLOCKED", "GIT_OR_SOURCE_PROOF_UNAVAILABLE")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-repo", type=Path, required=True)
    parser.add_argument("--v6-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fetch-original", action="store_true")
    args = parser.parse_args()
    result = evaluate_postsettlement(
        private_repo=args.private_repo,
        v6_repo=args.v6_repo,
        fetch_original=args.fetch_original,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("STAGECD_SAFE_STATUS=" + result["status"])
    print("STAGECD_SAFE_REASON=" + result["reason"])


if __name__ == "__main__":
    main()
