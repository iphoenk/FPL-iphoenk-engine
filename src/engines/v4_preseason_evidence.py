from __future__ import annotations

from pathlib import Path

from src.utils import DATA, read_json

EVIDENCE = DATA / "evidence" / "preseason_v4.json"


def attach_preseason_evidence(predictions: dict, path: Path = EVIDENCE) -> dict:
    """Attach verified preseason evidence without fabricating unavailable observations.

    The capability is deliberately evidence-gated. A missing materialized evidence file
    creates an explicit UNAVAILABLE state and no decision mutation. When verified rows
    are supplied, they are joined by canonical Official element id and exposed in each
    player's priors for downstream role/xMins consumers. This layer never mutates xPts
    directly and never treats regular-season matches as preseason evidence.
    """
    payload = read_json(path, {})
    rows = list(payload.get("players") or []) if isinstance(payload, dict) else []
    verified_rows = [
        row for row in rows
        if isinstance(row, dict)
        and row.get("element") is not None
        and row.get("source")
        and row.get("verified_at")
    ]
    by_id = {int(row["element"]): row for row in verified_rows}
    matched = 0
    role_rows = 0
    minute_rows = 0
    for player in predictions.get("players") or []:
        evidence = by_id.get(int(player.get("element") or 0))
        priors = player.setdefault("priors", {})
        if evidence is None:
            priors["preseason_evidence_state"] = "UNAVAILABLE"
            continue
        matched += 1
        role_rows += int(bool(evidence.get("role")))
        minute_rows += int(evidence.get("minutes") is not None)
        priors["preseason_evidence_state"] = "VERIFIED"
        priors["preseason"] = {
            "minutes": evidence.get("minutes"),
            "starts": evidence.get("starts"),
            "goals": evidence.get("goals"),
            "assists": evidence.get("assists"),
            "role": evidence.get("role"),
            "source": evidence.get("source"),
            "verified_at": evidence.get("verified_at"),
        }
    coverage = predictions.setdefault("input_coverage", {})
    coverage["preseason"] = str(path) if path.exists() else None
    coverage["preseason_contract"] = "PRESEASON_EVIDENCE_V1"
    coverage["preseason_consumer_active"] = True
    coverage["preseason_matched"] = matched
    coverage["preseason_role_rows"] = role_rows
    coverage["preseason_minutes_rows"] = minute_rows
    coverage["preseason_evidence_state"] = "VERIFIED" if matched else "EVIDENCE_GATED"
    coverage["preseason_direct_xpts_mutation"] = False
    return predictions
