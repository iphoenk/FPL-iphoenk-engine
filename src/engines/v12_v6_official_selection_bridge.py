"""Read-only V6 retrospective Official FPL GW partitions -> canonical P(start) shadow.

Only finished fixtures with explicit Official FPL `starts` are admitted.
Missing starter fields, BLANK and incomplete coverage fail closed. Retrospective
results are NEVER interpreted as predeadline prediction snapshots.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Mapping

from src.engines.v12_player_minutes import build_player_selection_evidence, estimate_player_minutes


def _utc(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def evaluate_v6_official_history_shadow(
    player: Mapping,
    partitions: list[Mapping],
    *,
    target_gw: int,
    evidence_cutoff_at: str,
    target_deadline_at: str,
) -> dict:
    """Produce V12 shadow probabilities from independently retrieved V6 JSON.

    No synthetic Git receipt is created. A locally deterministic hash is
    calculated from the accepted V6 partition bytes, but is NOT a signed
    original-Git-readback proof. The canonical adapter remains fail-closed
    until the caller supplies independently authenticated receipt.
    """
    pid = player.get("id") if isinstance(player, Mapping) else None
    cutoff = _utc(evidence_cutoff_at)
    deadline = _utc(target_deadline_at)
    rejects = defaultdict(int)
    if not isinstance(pid, int) or isinstance(pid, bool) or pid < 1 or not isinstance(target_gw, int) or not 1 <= target_gw <= 38 or not cutoff or not deadline or cutoff >= deadline:
        return {"status": "UNVERIFIED", "reason": "PLAYER_OR_GW_OR_CUTOFF_INVALID", "shadow_only": True}
    records = []
    accepted = []
    for part in partitions:
        if not isinstance(part, Mapping) or part.get("authority") != "OFFICIAL_FPL" or part.get("contract") != "OFFICIAL_FPL_RETROSPECTIVE_GW_PARTITION_V1":
            rejects["UNTRUSTED_PARTITION"] += 1
            continue
        gw = part.get("gw")
        if not isinstance(gw, int) or isinstance(gw, bool) or gw >= target_gw or gw < 1 or part.get("coverage", {}).get("status") != "PASS" or part.get("coverage", {}).get("gw_official_finalized") is not True or part.get("coverage", {}).get("fixture_identity_status") != "PASS":
            rejects["NOT_FINALIZED_OR_FUTURE"] += 1
            continue
        asof = _utc(part.get("original_full_history_generated_at"))
        if asof is None or asof > cutoff:
            rejects["AFTER_CUTOFF"] += 1
            continue
        record = part.get("players", {}).get(str(pid))
        if not isinstance(record, Mapping) or record.get("element_id") != pid or record.get("status") not in ("FINAL", "DNP"):
            rejects["PLAYER_ABSENT_OR_BLANK"] += 1
            continue
        fixtures = record.get("fixtures")
        if not isinstance(fixtures, list) or not fixtures:
            rejects["NO_FIXTURES"] += 1
            continue
        for fixture in fixtures:
            if not isinstance(fixture, Mapping) or fixture.get("element") != pid or not isinstance(fixture.get("fixture"), int) or not isinstance(fixture.get("starts"), int) or isinstance(fixture.get("starts"), bool) or fixture["starts"] not in (0, 1) or not isinstance(fixture.get("minutes"), int) or isinstance(fixture.get("minutes"), bool):
                rejects["FIXTURE_SELECTION_INVALID"] += 1
                continue
            minutes = fixture["minutes"]
            started = fixture["starts"] == 1
            if not 0 <= minutes <= 130 or (started and minutes == 0):
                rejects["FIXTURE_MINUTES_INVALID"] += 1
                continue
            if record["status"] == "DNP" and (minutes or started):
                rejects["DNP_CONTRADICTION"] += 1
                continue
            records.append({"gw": gw, "fixture": fixture["fixture"], "starter": started, "minutes": minutes})
        accepted.append(gw)
    selection = build_player_selection_evidence(player, [
        {"gw": x["gw"], "match_id": str(x["fixture"]), "starter": x["starter"],
         "minutes": x["minutes"], "official_status": "FINAL" if x["minutes"] else "DNP"}
        for x in records
    ]) if len(records) >= 3 else {"status": "INSUFFICIENT_EVIDENCE"}
    estimate = None
    if selection.get("status") == "AVAILABLE":
        enriched = dict(player)
        enriched["starts"] = selection["starts"]
        enriched["minutes"] = selection["minutes"]
        estimate = estimate_player_minutes(enriched, {
            "team_matches_played": len(records), "selection_evidence": selection,
        })
    # Do not claim authenticated original Git source from arbitrary input.
    return {
        "contract": "V6_OFFICIAL_HISTORY_SHADOW_BRIDGE_V1",
        "status": "READY_SHADOW_UNATTESTED" if estimate else "INSUFFICIENT_EVIDENCE",
        "player_id": pid,
        "target_gw": target_gw,
        "verified_local_fixture_rows": len(records),
        "accepted_gws": sorted(set(accepted)),
        "rejected": dict(sorted(rejects.items())),
        "local_payload_sha256": sha256(json.dumps(records,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
        "probabilities": ({
            "p_start": estimate["start_probability"],
            "p_regular_cameo": estimate["regular_cameo_probability"],
            "p_late_cameo": estimate["late_cameo_probability"],
            "p_dnp": estimate["dnp_probability"],
        } if estimate else None),
        "expected_minutes": estimate["expected_minutes"] if estimate else None,
        "calibration": "NOT_VERIFIED",
        "source_authentication": "NOT_ATTESTED",
        "shadow_only": True,
        "eligible_for_live_scoring": False,
        "publication_authorized": False,
    }
