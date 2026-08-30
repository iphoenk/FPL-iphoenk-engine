from __future__ import annotations

from pathlib import Path

from src.utils import DATA, parse_dt, read_json

EVIDENCE = DATA / "evidence" / "preseason_v4.json"
CONTRACT = "PRESEASON_EVIDENCE_V1"
SEASON = "2026-27"
ALLOWED_ROLES = {
    "goalkeeper",
    "attacking_fullback",
    "central_defender",
    "hybrid_defender",
    "attacking_midfielder",
    "creator_midfielder",
    "holding_midfielder",
    "balanced_midfielder",
    "striker",
    "support_forward",
}


def load_verified_preseason_evidence(path: Path = EVIDENCE) -> tuple[dict[int, dict], dict]:
    """Load only verified, current-season evidence keyed by Official element id."""
    payload = read_json(path, {})
    contract_ok = (
        isinstance(payload, dict)
        and payload.get("contract") == CONTRACT
        and payload.get("season") == SEASON
    )
    rows = list(payload.get("players") or []) if contract_ok else []
    by_id: dict[int, dict] = {}
    rejected = 0
    for row in rows:
        if not isinstance(row, dict) or row.get("verified") is not True:
            rejected += 1
            continue
        try:
            element = int(row.get("element"))
        except (TypeError, ValueError):
            rejected += 1
            continue
        role = row.get("role")
        verified_at = parse_dt(row.get("verified_at"))
        if (
            element <= 0
            or not row.get("source")
            or verified_at is None
            or role not in ALLOWED_ROLES
        ):
            rejected += 1
            continue
        normalized = {
            "element": element,
            "role": role,
            "minutes": row.get("minutes"),
            "starts": row.get("starts"),
            "goals": row.get("goals"),
            "assists": row.get("assists"),
            "source": row.get("source"),
            "verified_at": verified_at.isoformat(),
            "verified": True,
        }
        previous = by_id.get(element)
        if previous is not None and previous != normalized:
            raise RuntimeError(f"conflicting verified preseason rows for element {element}")
        by_id[element] = normalized
    meta = {
        "preseason": str(path) if path.exists() else None,
        "preseason_contract": CONTRACT,
        "preseason_consumer_active": True,
        "preseason_materialized_rows": len(rows),
        "preseason_matched": len(by_id),
        "preseason_role_rows": sum(bool(row.get("role")) for row in by_id.values()),
        "preseason_minutes_rows": sum(row.get("minutes") is not None for row in by_id.values()),
        "preseason_rejected_rows": rejected,
        "preseason_evidence_state": "VERIFIED" if by_id else "EVIDENCE_GATED",
        "preseason_direct_xpts_mutation": False,
        "preseason_identity_join": "official_element_id",
    }
    return by_id, meta
