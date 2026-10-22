from __future__ import annotations

"""High-integrity Official FPL match-selection adapter for canonical P1.1.

Shadow-only: this module does NOT own a second probability model, does NOT
modify projections/optimizers and cannot authorize publication. The sole
numerical owner is V12_PLAYER_MINUTES. Upstream original Git receipt proof
must be independently authenticated: this adapter validates its contract,
not Git object signatures or the completeness of any remote source.
"""

from datetime import datetime, timezone
import math
import re
from typing import Any, Mapping, Sequence

from src.engines.v12_player_minutes import (
    build_player_selection_evidence,
    estimate_player_minutes,
)

SOURCE = "official_fpl"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
JOINS = frozenset({"EXACT", "VERIFIED", "VERIFIED_MANUAL"})
FINAL = frozenset({"FINAL", "DNP"})


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _valid_minutes(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) and 0 <= numeric <= 130 else None


def _empty(status: str, reasons: list[str], *, player_id: int | None, target_gw: int,
           rejected: Mapping[str, int] | None = None, verified: int = 0) -> dict[str, Any]:
    return {
        "contract": "V12_OFFICIAL_SELECTION_PROBABILITY_SHADOW_V1",
        "status": status,
        "player_id": player_id,
        "target_gw": target_gw,
        "verified_matches": verified,
        "rejected": dict(sorted((rejected or {}).items())),
        "reasons": sorted(set(reasons)),
        "probabilities": None,
        "minutes": None,
        "calibration": "NOT_VERIFIED",
        "model_owner": "V12_PLAYER_MINUTES",
        "shadow_only": True,
        "eligible_for_live_scoring": False,
        "publication_authorized": False,
    }


def evaluate_official_selection_shadow(
    player: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    receipt: Mapping[str, Any],
    *,
    target_gw: int,
    evidence_cutoff_at: str,
    target_deadline_at: str,
    min_verified_matches: int = 3,
) -> dict[str, Any]:
    """Estimate P(start), cameo and DNP with the EXISTING canonical estimator.

    Every row requires exact Official FPL ID/fixture binding, settled status,
    original-source fingerprint agreement and observation before the cutoff.
    Disagreement in two observations of one fixture quarantines that fixture.
    The required receipt is checked for shape and timestamp; it must originate
    from the governed, authenticated V6 original Git readback upstream.

    A result is never a production or calibrated probability: the caller
    must not publish it to lineup, transfer, C/VC or V12 engine inputs.
    """
    if not isinstance(player, Mapping):
        player = {}
    if not isinstance(receipt, Mapping):
        receipt = {}
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        rows = []
    pid = _int(player.get("id"))
    cutoff = _time(evidence_cutoff_at)
    deadline = _time(target_deadline_at)
    source_time = _time(receipt.get("observed_at")) if isinstance(receipt, Mapping) else None
    digest = receipt.get("artifact_sha256") if isinstance(receipt, Mapping) else None
    rejected: dict[str, int] = {}

    def reject(key: str) -> None:
        rejected[key] = rejected.get(key, 0) + 1

    reasons: list[str] = []
    if pid is None or _int(target_gw) is None or not 1 <= target_gw <= 38:
        reasons.append("TARGET_OR_PLAYER_INVALID")
    if not (cutoff and deadline and cutoff < deadline):
        reasons.append("TARGET_PREDEADLINE_CUTOFF_INVALID")
    if not (receipt.get("source_id") == SOURCE
            and receipt.get("original_git_readback") == "PASS"
            and isinstance(digest, str) and SHA256.fullmatch(digest)
            and source_time and cutoff and source_time <= cutoff):
        reasons.append("ORIGINAL_OFFICIAL_SOURCE_RECEIPT_UNVERIFIED")
    if not isinstance(min_verified_matches, int) or isinstance(min_verified_matches, bool) or min_verified_matches < 1:
        reasons.append("MIN_SAMPLE_INVALID")
    if reasons:
        return _empty("UNVERIFIED", reasons, player_id=pid, target_gw=target_gw)

    seen: dict[int, dict[str, Any]] = {}
    conflicted: set[int] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            reject("INVALID_ROW")
            continue
        eid = _int(raw.get("official_element_id"))
        fid = _int(raw.get("official_fixture_id"))
        gw = _int(raw.get("gw"))
        if eid != pid or fid is None or gw is None or gw >= target_gw:
            reject("PLAYER_FIXTURE_OR_GW_IDENTITY_MISMATCH")
            continue
        if (raw.get("source_id") != SOURCE
                or raw.get("source_snapshot_sha256") != digest
                or str(raw.get("identity_status") or "").upper() not in JOINS
                or str(raw.get("fixture_identity_status") or "").upper() not in JOINS
                or raw.get("fixture_finished") is not True
                or str(raw.get("official_status") or "").upper() not in FINAL):
            reject("OFFICIAL_FINAL_SOURCE_BINDING_MISSING")
            continue
        observed = _time(raw.get("observed_at"))
        if observed is None or observed > cutoff or (source_time and observed > source_time):
            reject("ROW_NOT_OBSERVED_PREDEADLINE")
            continue
        starter = raw.get("starter")
        minutes = _valid_minutes(raw.get("minutes"))
        if not isinstance(starter, bool) or minutes is None or (starter and minutes == 0):
            reject("SELECTION_RESULT_INVALID")
            continue
        if str(raw.get("official_status") or "").upper() == "DNP" and (starter or minutes != 0):
            reject("OFFICIAL_DNP_CONTRADICTION")
            continue
        normalized = {
            "gw": gw, "match_id": str(fid), "starter": starter,
            "minutes": minutes, "official_status": str(raw["official_status"]).upper(),
        }
        if fid in conflicted:
            reject("CONFLICTED_FIXTURE")
            continue
        prior = seen.get(fid)
        if prior is None:
            seen[fid] = normalized
        elif prior == normalized:
            reject("DUPLICATE_SAME_OBSERVATION")
        else:
            conflicted.add(fid)
            seen.pop(fid, None)
            reject("CONFLICTED_FIXTURE")

    verified_rows = sorted(seen.values(), key=lambda row: (row["gw"], row["match_id"]))
    if len(verified_rows) < min_verified_matches:
        return _empty(
            "INSUFFICIENT_VERIFIED_EVIDENCE", ["MIN_VERIFIED_MATCH_COUNT_NOT_MET"],
            player_id=pid, target_gw=target_gw, rejected=rejected,
            verified=len(verified_rows),
        )

    selection = build_player_selection_evidence(player, verified_rows)
    if selection.get("status") != "AVAILABLE":
        return _empty("INSUFFICIENT_VERIFIED_EVIDENCE",
                      ["CANONICAL_SELECTION_EVIDENCE_UNAVAILABLE"],
                      player_id=pid, target_gw=target_gw,
                      rejected=rejected, verified=len(verified_rows))
    p = dict(player)
    p["starts"] = selection["starts"]
    p["minutes"] = selection["minutes"]
    # No inferred role, manager, rotation, future injury or fabricated prior.
    context = {
        "team_matches_played": len(verified_rows),
        "selection_evidence": selection,
    }
    estimate = estimate_player_minutes(p, context)
    return {
        **_empty("READY_SHADOW", [], player_id=pid, target_gw=target_gw,
                 rejected=rejected, verified=len(verified_rows)),
        "selection_evidence": {
            "observed_matches": selection["observed_matches"],
            "starts": selection["starts"],
            "dnp": selection["dnp"],
            "start_rate": selection["start_rate"],
            "selection_posterior": selection["selection_posterior"],
        },
        "probabilities": {
            "p_start": estimate["start_probability"],
            "p_regular_cameo": estimate["regular_cameo_probability"],
            "p_late_cameo": estimate["late_cameo_probability"],
            "p_dnp": estimate["dnp_probability"],
        },
        "minutes": {
            "expected": estimate["expected_minutes"],
            "interval": estimate.get("expected_minutes_interval"),
        },
        "model_confidence": estimate["confidence"],
        "source": {
            "source_id": SOURCE,
            "artifact_sha256": digest,
            "observed_at": source_time.isoformat(),
            "evidence_cutoff_at": cutoff.isoformat(),
            "original_git_readback": "PASS",
            "original_git_readback_reverified_locally": False,
        },
    }
