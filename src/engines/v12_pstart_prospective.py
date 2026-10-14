from __future__ import annotations

"""Prospective P(start) evidence, emitted by the existing DEEP occurrence only.

This is a paired, frozen evidence surface, not a new mathematical owner or
scheduler. A private remote Git readback is needed to admit a forecast.
"""

from datetime import datetime, timezone
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

from src.engines.v12_player_minutes import estimate_player_minutes
from src.models.v12_pstart_context_evidence import build_pstart_context_observability

CONTRACT = "V12_PSTART_PROSPECTIVE_PREDEADLINE_V1"
POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


class ProspectiveCaptureError(ValueError):
    pass


def _utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ProspectiveCaptureError("OFFICIAL_DEADLINE_MISSING")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProspectiveCaptureError("OFFICIAL_DEADLINE_INVALID") from exc
    if parsed.tzinfo is None:
        raise ProspectiveCaptureError("OFFICIAL_DEADLINE_NAIVE")
    return parsed.astimezone(timezone.utc)


def _sha(path: Path) -> str:
    if not path.is_file():
        raise ProspectiveCaptureError("V6_SOURCE_FILE_MISSING")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_original_v6_inputs(
    runtime_data_root: Path,
    input_sha: Mapping[str, str],
    captured_at: datetime,
) -> dict[str, Any]:
    """Read the original immutable V6 commit and compare source file digests.

    A working-tree hash alone is insufficient. No active network is needed:
    the runner's authenticated V6 checkout already contains the Git objects.
    A separate post-publish private Git readback remains mandatory.
    """
    def git(*args: str) -> bytes:
        try:
            return subprocess.check_output(
                ["git", "-C", str(runtime_data_root), *args], stderr=subprocess.DEVNULL
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            raise ProspectiveCaptureError("ORIGINAL_V6_GIT_OBJECT_UNAVAILABLE") from exc

    origin_commit = git("rev-parse", "HEAD").decode("utf-8").strip()
    if len(origin_commit) != 40 or any(c not in "0123456789abcdef" for c in origin_commit):
        raise ProspectiveCaptureError("ORIGINAL_V6_COMMIT_IDENTITY_INVALID")
    commit_at = _utc(git("show", "-s", "--format=%cI", origin_commit).decode("utf-8").strip())
    if commit_at > captured_at:
        raise ProspectiveCaptureError("SOURCE_COMMIT_AFTER_CAPTURE")
    for path, expected in sorted(input_sha.items()):
        if path not in {
            "data/v6/current/official_fpl.json",
            "data/v6/normalized/sources/official_fpl.json",
        }:
            raise ProspectiveCaptureError("SOURCE_PATH_NOT_ALLOWLISTED")
        obj = git("show", f"{origin_commit}:{path}")
        if hashlib.sha256(obj).hexdigest() != expected:
            raise ProspectiveCaptureError("V6_ORIGINAL_GIT_BLOB_SHA_MISMATCH")
    return {
        "git_commit": origin_commit,
        "git_commit_at": commit_at.isoformat(),
        "git_object_readback": "PASS",
        "readback_source_file_sha256": dict(input_sha),
        "private_remote_readback": "UNVERIFIED",
    }


def _predictive_fields(raw: Mapping[str, Any]) -> dict[str, float]:
    result = {}
    for name in ("start_probability", "expected_minutes", "dnp_probability", "cameo_probability"):
        value = raw.get(name)
        if not isinstance(value, (float, int)) or isinstance(value, bool):
            raise ProspectiveCaptureError("CANONICAL_PLAYER_FORECAST_INCOMPLETE")
        result[name] = float(value)
    return result


def build_prospective_capture(
    *,
    bootstrap: Mapping[str, Any],
    projections: Mapping[str, Any],
    strength: Mapping[str, Any],
    foundation: Mapping[str, Any],
    runtime_data_root: Path,
    report_slot: str,
    prefetch_run_id: str,
    model_sha: str,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Read-only paired forecast that must be committed before target deadline.

    Exact timestamp is observed at creation, never backdated to report_slot.
    GW outcomes are not consumed; true holdout requires a future settlement.
    """
    if not isinstance(projections, Mapping):
        raise ProspectiveCaptureError("PROJECTION_UNAVAILABLE")
    now = observed_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ProspectiveCaptureError("CAPTURE_TIMESTAMP_NAIVE")
    now = now.astimezone(timezone.utc)
    gw = int(projections.get("planning_gw") or 0)
    event = next(
        (e for e in bootstrap.get("events") or []
         if isinstance(e, Mapping) and int(e.get("id") or 0) == gw),
        None,
    )
    if not event or event.get("finished") is True:
        raise ProspectiveCaptureError("CURRENT_OFFICIAL_EVENT_UNAVAILABLE")
    deadline = _utc(event.get("deadline_time"))
    if now >= deadline:
        raise ProspectiveCaptureError("NO_PREDEADLINE_CAPTURE")
    if not model_sha or not prefetch_run_id or not report_slot:
        raise ProspectiveCaptureError("OCCURRENCE_LINEAGE_INCOMPLETE")
    if int(projections.get("planning_gw") or 0) != gw or gw <= 0:
        raise ProspectiveCaptureError("GW_BINDING_INVALID")

    official = {
        int(p["id"]): p for p in bootstrap.get("elements") or []
        if isinstance(p, Mapping) and int(p.get("id") or 0) > 0
    }
    selected = [
        p for p in projections.get("players") or []
        if isinstance(p, Mapping)
    ]
    if len(selected) != len(official) or not official or len(official) != len(bootstrap.get("elements") or []):
        raise ProspectiveCaptureError("UNIVERSE_INCOMPLETE")
    ids = [int(row.get("element") or 0) for row in selected]
    if len(set(ids)) != len(ids) or set(ids) != set(official):
        raise ProspectiveCaptureError("UNIVERSE_IDENTITY_MISMATCH")

    source_path = Path("data/v6/normalized/sources/official_fpl.json")
    current_path = Path("data/v6/current/official_fpl.json")
    source = json.loads((runtime_data_root / source_path).read_text(encoding="utf-8"))
    source_ids = source.get("source_snapshot_ids") or []
    if not isinstance(source_ids, list) or not source_ids:
        raise ProspectiveCaptureError("V6_SNAPSHOT_IDENTITIES_UNAVAILABLE")
    if source.get("source_id") != "official_fpl":
        raise ProspectiveCaptureError("V6_SOURCE_IDENTITY_MISMATCH")
    input_sha = {
        current_path.as_posix(): _sha(runtime_data_root / current_path),
        source_path.as_posix(): _sha(runtime_data_root / source_path),
    }
    original_source_git = _verify_original_v6_inputs(
        runtime_data_root, input_sha, now
    )
    rows_by_element: dict[int, list[dict[str, Any]]] = {}
    for row in foundation.get("player_match_rows") or []:
        if isinstance(row, Mapping):
            pid = int(row.get("player_id") or row.get("element") or 0)
            if pid > 0:
                rows_by_element.setdefault(pid, []).append(dict(row))
    team_matches = {
        int(row.get("team_id") or 0): int(row.get("matches_played") or 0)
        for row in strength.get("teams") or []
        if isinstance(row, Mapping)
    }
    output = []
    for projected in selected:
        pid = int(projected["element"])
        player = dict(official[pid])
        observed = projected.get("current_season") or {}
        selection = projected.get("selection_evidence") or {}
        if selection.get("status") == "AVAILABLE":
            player["starts"] = observed.get("starts")
            player["minutes"] = observed.get("minutes")
        context: dict[str, Any] = {
            "team_matches_played": team_matches.get(int(player.get("team") or 0), 0),
            "player_match_rows": rows_by_element.get(pid, []),
        }
        evidence = projected.get("availability_evidence")
        if isinstance(evidence, Mapping):
            context["availability_evidence_state"] = dict(evidence)
        historical = projected.get("historical_prior") or {}
        if historical:
            context.update({
                "prior_start_probability": historical.get("start_probability"),
                "starter_minutes_prior": historical.get("avg_minutes_when_start"),
                "prior_evidence_minutes": historical.get("minutes"),
                "prior_source": historical.get("source"),
                "prior_identity_match": historical.get("identity_match"),
            })
        # One existing owner, two deliberately paired contexts. No fit claims
        # or free-form injury observations are converted to numeric odds.
        baseline = _predictive_fields(estimate_player_minutes(player, context))
        individualized = _predictive_fields(projected.get("xmins") or {})
        xmins = projected.get("xmins") or {}
        source_evidence = xmins.get("p_start_evidence") or projected.get("p_start_evidence")
        # Freeze source-bound features alongside the forecast. External role
        # and manager profiles remain advisory without original as-of lineage.
        feature_snapshot = build_pstart_context_observability(
            {**projected, "status": player.get("status")},
            xmins,
            source_evidence if isinstance(source_evidence, Mapping) else None,
        )
        feature_snapshot["readiness"].update({
            "official_fpl_source_original_git_readback": "PASS",
            "external_role_asof_git_readback": "UNVERIFIED",
            "external_manager_asof_git_readback": "UNVERIFIED",
            "numeric_shadow_prediction_created": False,
            "historical_retrofit": False,
        })
        output.append({
            "element": pid,
            "position": POSITIONS[int(player.get("element_type") or 0)],
            "team_id": int(player.get("team") or 0),
            "baseline": baseline,
            "individualized": individualized,
            "selection_status": selection.get("status") or "MISSING",
            "selection_observed_matches": selection.get("observed_matches"),
            "role_manager_fit": "ADVISORY_UNCALIBRATED",
            "context_evidence": feature_snapshot,
        })
    output.sort(key=lambda p: p["element"])
    rows_sha = hashlib.sha256(
        json.dumps(output, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "contract": CONTRACT,
        "status": "CAPTURED_AWAITING_IMMUTABLE_REMOTE_READBACK",
        "planning_gw": gw,
        "report_slot": report_slot,
        "captured_at": now.isoformat(),
        "official_deadline": deadline.isoformat(),
        "model_sha": model_sha,
        "model_owner": "V12_PLAYER_MINUTES",
        "calibration": "PENDING_FUTURE_GW_SETTLEMENT",
        "source_authority": "V6",
        "source": {
            "id": "official_fpl",
            "snapshot_ids": source_ids,
            "prefetch_run_id": prefetch_run_id,
            "source_file_sha256": input_sha,
            "identity_verified_by_original_git_readback": True,
            "original_git_evidence": original_source_git,
        },
        "universe_expected": len(official),
        "universe_observed": len(output),
        "positions": {pos: sum(x["position"] == pos for x in output)
                      for pos in ("GK", "DEF", "MID", "FWD")},
        "forecast_rows_sha256": rows_sha,
        "forecast_rows": output,
        "context_evidence_summary": {
            "contract": "V12_GW7_CONTEXT_SHADOW_CAPTURE_V1",
            "official_status_original_git_verified": sum(
                row["context_evidence"]["availability"]["official_status_observed"]
                for row in output
            ),
            "advisory_role_profiles": sum(
                row["context_evidence"]["role"]["status"] == "PROFILE_ADVISORY_UNCALIBRATED"
                for row in output
            ),
            "manager_timeline_eligible": 0,
            "external_role_asof_git_readback": "UNVERIFIED",
            "external_manager_asof_git_readback": "UNVERIFIED",
            "may_promote_context_probability": False,
            "shadow_observation_only": True,
        },
        "governance": {
            "current_only": True,
            "never_retrofit_previous_gws": True,
            "source_checked_at_is_not_historical_finalization": True,
            "readback_required_before_admission": True,
            "one_canonical_math_owner": True,
            "no_new_scheduler": True,
            "no_parameter_retuning": True,
            "calibration_requires_future_finished_gw": True,
        },
    }
