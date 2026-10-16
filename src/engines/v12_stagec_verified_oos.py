"""Immutable Git-backed prospective GW7 out-of-sample replay (shadow only).

No historical retrofit and no new scheduled trigger. Run only after the
target event is finalized in governed V6 original Git source objects.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from src.models.v12_stagec_temporal_oos import audit_oos_calibration

SHA = re.compile(r"^[0-9a-f]{40}$")
OCCURRENCE = re.compile(r"^reports/2026-27/gw_[0-9]+/[0-9]{8}_[0-9]{4,6}_plus_0700$")


class StageCOOSReplayError(ValueError):
    """Fail closed without modifying private or immutable inputs."""


def _time(value: Any) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise StageCOOSReplayError("TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None:
        raise StageCOOSReplayError("TIMESTAMP_NAIVE")
    return dt.astimezone(timezone.utc)


def _git(repo: Path, *args: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise StageCOOSReplayError("ORIGINAL_GIT_OBJECT_UNAVAILABLE") from exc


def _git_object(repo: Path, commit: str, path: str) -> bytes:
    if not isinstance(commit, str) or not SHA.fullmatch(commit):
        raise StageCOOSReplayError("GIT_COMMIT_INVALID")
    if Path(path).is_absolute() or ".." in Path(path).parts:
        raise StageCOOSReplayError("GIT_OBJECT_PATH_INVALID")
    return _git(repo, "show", f"{commit}:{path}")


def _commit_time(repo: Path, commit: str) -> datetime:
    if not isinstance(commit, str) or not SHA.fullmatch(commit):
        raise StageCOOSReplayError("GIT_COMMIT_INVALID")
    return _time(_git(repo, "show", "-s", "--format=%cI", commit).decode().strip())


def _json(raw: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise StageCOOSReplayError(f"{label}_INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise StageCOOSReplayError(f"{label}_NOT_MAPPING")
    return value


def run_verified_stagec_oos(
    *,
    private_repo: Path,
    private_commit: str,
    occurrence_path: str,
    v6_repo: Path,
    settled_v6_commit: str,
    expected_universe: int = 667,
    minimum_sample: int = 50,
) -> dict[str, Any]:
    """Score one frozen GW forecast against a later, final V6 original commit.

    Git show, original commit times, private receipt and source digests are
    independently verified. The output is aggregate-only and shadow-only.
    """
    if not isinstance(occurrence_path, str) or not OCCURRENCE.fullmatch(occurrence_path):
        raise StageCOOSReplayError("OCCURRENCE_PATH_INVALID")
    if expected_universe <= 0 or minimum_sample < 50:
        raise StageCOOSReplayError("UNIVERSE_OR_SAMPLE_POLICY_INVALID")
    receipt = _json(
        _git_object(private_repo, private_commit, occurrence_path + "/delivery_receipt.json"),
        "RECEIPT",
    )
    required = (
        ("delivery_status", "READY_FULL"),
        ("private_remote_readback", "PASS"),
        ("pstart_prospective_remote_readback", "PASS"),
        ("pstart_prospective_source_sha256_readback", "PASS"),
        ("pstart_prospective_status", "IMMUTABLE_REMOTE_READBACK_VERIFIED"),
    )
    if any(receipt.get(k) != v for k, v in required):
        raise StageCOOSReplayError("IMMUTABLE_PROSPECTIVE_RECEIPT_UNVERIFIED")
    original_commit = receipt.get("pstart_prospective_private_commit")
    frozen_path = occurrence_path + "/pstart_predeadline_forecast.json"
    original_bytes = _git_object(private_repo, original_commit, frozen_path)
    final_bytes = _git_object(private_repo, private_commit, frozen_path)
    original_sha = hashlib.sha256(original_bytes).hexdigest()
    if original_bytes != final_bytes or original_sha != receipt.get("pstart_prospective_sha256"):
        raise StageCOOSReplayError("FROZEN_FORECAST_BYTES_CHANGED")
    forecast = _json(original_bytes, "FORECAST")
    if forecast.get("contract") != "V12_PSTART_PROSPECTIVE_PREDEADLINE_V1":
        raise StageCOOSReplayError("FROZEN_FORECAST_CONTRACT_INVALID")
    gw = forecast.get("planning_gw")
    if type(gw) is not int or gw <= 0 or (
        f"/gw_{gw}/" not in occurrence_path
    ):
        raise StageCOOSReplayError("FROZEN_GW_IDENTITY_INVALID")
    if (
        forecast.get("model_owner") != "V12_PLAYER_MINUTES"
        or forecast.get("model_sha") != receipt.get("model_sha")
        or forecast.get("report_slot") != receipt.get("report_slot")
        or gw != receipt.get("planning_gw")
    ):
        raise StageCOOSReplayError("MODEL_OR_OCCURRENCE_MISMATCH")
    captured = _time(forecast.get("captured_at"))
    deadline = _time(forecast.get("official_deadline"))
    if captured >= deadline or _commit_time(private_repo, original_commit) >= deadline:
        raise StageCOOSReplayError("FROZEN_FORECAST_NOT_PREDEADLINE")
    if _commit_time(private_repo, original_commit) < captured:
        raise StageCOOSReplayError("FORECAST_COMMIT_BEFORE_CAPTURE")
    source = forecast.get("source") or {}
    if not isinstance(source, Mapping) or (
        source.get("id") != "official_fpl"
        or (source.get("original_git_evidence") or {}).get("git_object_readback") != "PASS"
    ):
        raise StageCOOSReplayError("FROZEN_V6_SOURCE_PROOF_MISSING")
    rows = forecast.get("forecast_rows")
    if not isinstance(rows, list) or (
        len(rows) != expected_universe
        or forecast.get("universe_expected") != expected_universe
        or forecast.get("universe_observed") != expected_universe
    ):
        raise StageCOOSReplayError("FROZEN_FULL_UNIVERSE_MISSING")
    ids = [row.get("element") for row in rows if isinstance(row, Mapping)]
    if len(ids) != expected_universe or any(type(i) is not int or i <= 0 for i in ids) or len(set(ids)) != len(ids):
        raise StageCOOSReplayError("FROZEN_PLAYER_IDENTITIES_INVALID")
    normalized_rows_digest = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if normalized_rows_digest != forecast.get("forecast_rows_sha256"):
        raise StageCOOSReplayError("FROZEN_ROWS_DIGEST_MISMATCH")

    normalized_raw = _git_object(
        v6_repo, settled_v6_commit, "data/v6/normalized/sources/official_fpl.json"
    )
    fixture_raw = _git_object(
        v6_repo, settled_v6_commit, "data/v6/normalized/canonical_fixtures.json"
    )
    normalized = _json(normalized_raw, "SETTLED_V6")
    fixtures = _json(fixture_raw, "SETTLED_FIXTURES")
    if (
        normalized.get("source_id") != "official_fpl"
        or fixtures.get("authority") != "official_fpl"
        or gw not in ((normalized.get("history_coverage") or {}).get("finished_gws") or [])
    ):
        raise StageCOOSReplayError("TARGET_GW_NOT_SETTLED_IN_V6")
    if _commit_time(v6_repo, settled_v6_commit) <= deadline:
        raise StageCOOSReplayError("SETTLED_COMMIT_NOT_AFTER_DEADLINE")
    settled_at = _time(normalized.get("effective_at"))
    match_map: dict[int, Mapping[str, Any]] = {}
    team_map: dict[int, int] = {}
    for fixture in fixtures.get("fixtures") or []:
        if fixture.get("event") != gw:
            continue
        fid, h, a = fixture.get("official_fpl_fixture_id"), fixture.get("team_h"), fixture.get("team_a")
        if any(type(v) is not int or v <= 0 for v in (fid, h, a)) or fid in match_map or h == a:
            raise StageCOOSReplayError("SETTLED_FIXTURE_IDENTITY_INVALID")
        if fixture.get("identity_authority") != "official_fpl" or fixture.get("finished") is not True:
            raise StageCOOSReplayError("TARGET_GW_FIXTURE_UNFINISHED")
        kickoff = _time(fixture.get("kickoff_time"))
        if not captured < kickoff < settled_at:
            raise StageCOOSReplayError("FROZEN_FIXTURE_TEMPORAL_LEAKAGE")
        if h in team_map or a in team_map:
            raise StageCOOSReplayError("GW_MULTI_FIXTURE_NEEDS_PER_MATCH_FORECAST")
        team_map[h] = fid
        team_map[a] = fid
        match_map[fid] = fixture
    if not match_map:
        raise StageCOOSReplayError("TARGET_GW_NO_VERIFIED_FIXTURES")
    outcomes: dict[int, Mapping[str, Any]] = {}
    for raw in ((normalized.get("record_groups") or {}).get("player_matches") or []):
        if raw.get("gw") != gw:
            continue
        pid = raw.get("official_element_id")
        if type(pid) is not int or pid <= 0 or pid in outcomes:
            raise StageCOOSReplayError("SETTLED_PLAYER_IDENTITY_INVALID_OR_DUPLICATE")
        if (
            raw.get("identity_status") != "EXACT"
            or raw.get("fixture_identity_status") != "EXACT"
            or raw.get("dataset") != "event_live"
            or raw.get("source") != "official_fpl"
            or type(raw.get("starter")) is not bool
        ):
            raise StageCOOSReplayError("SETTLED_PLAYER_OUTCOME_NOT_VERIFIED")
        fid = raw.get("official_fixture_id")
        if fid not in match_map or team_map.get(raw.get("team_id")) != fid:
            raise StageCOOSReplayError("SETTLED_PLAYER_FIXTURE_MISMATCH")
        observed = _time(raw.get("source_checked_at"))
        if not _time(raw.get("kickoff_time")) == _time(match_map[fid].get("kickoff_time")):
            raise StageCOOSReplayError("SETTLED_KICKOFF_IDENTITY_MISMATCH")
        if not _time(match_map[fid].get("kickoff_time")) < observed <= settled_at:
            raise StageCOOSReplayError("SETTLED_OUTCOME_TIMING_INVALID")
        outcomes[pid] = raw
    if set(outcomes) != set(ids):
        raise StageCOOSReplayError("SETTLED_UNIVERSE_OUTCOMES_MISSING_OR_FOREIGN")

    predicted, actual = [], []
    for row in rows:
        pid = row["element"]
        result = outcomes[pid]
        fixture = match_map[result["official_fixture_id"]]
        baseline, individualized = row.get("baseline"), row.get("individualized")
        if not isinstance(baseline, Mapping) or not isinstance(individualized, Mapping):
            raise StageCOOSReplayError("FROZEN_PAIRED_BASELINE_MISSING")
        if row.get("team_id") != result.get("team_id"):
            raise StageCOOSReplayError("FROZEN_TEAM_IDENTITY_DRIFT")
        match_id = str(result["official_fixture_id"])
        predicted.append({
            "element": pid,
            "match_id": match_id,
            "prediction_as_of": forecast["captured_at"],
            "kickoff": fixture["kickoff_time"],
            "p_start": individualized.get("start_probability"),
            "xmins": individualized.get("expected_minutes"),
            "baseline_p_start": baseline.get("start_probability"),
            "baseline_xmins": baseline.get("expected_minutes"),
            "model_owner": "V12_PLAYER_MINUTES",
        })
        actual.append({
            "element": pid,
            "match_id": match_id,
            "settled_at": result["source_checked_at"],
            "starter": result["starter"],
            "minutes": result["minutes"],
        })
    scored = audit_oos_calibration(predicted, actual, minimum_sample=minimum_sample)
    if scored["scored_sample"] != expected_universe or scored["rejected_by_reason"]:
        raise StageCOOSReplayError("SETTLED_OOS_ROWS_NOT_ALL_ADMITTED")
    return {
        **scored,
        "evidence_status": "IMMUTABLE_FROZEN_AND_SETTLED_V6_READBACK_PASS",
        "planning_gw": gw,
        "original_forecast_git_commit": original_commit,
        "original_forecast_sha256": original_sha,
        "original_forecast_rows_sha256": normalized_rows_digest,
        "settled_v6_git_commit": settled_v6_commit,
        "settled_v6_normalized_sha256": hashlib.sha256(normalized_raw).hexdigest(),
        "settled_v6_fixtures_sha256": hashlib.sha256(fixture_raw).hexdigest(),
        "prediction_capture": forecast["captured_at"],
        "official_deadline": forecast["official_deadline"],
        "future_data_retrofit": False,
        "new_scheduler": False,
        "production_activation_allowed": False,
    }
