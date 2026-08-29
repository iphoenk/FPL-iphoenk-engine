from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from src.utils import CONFIG, DATA, atomic_json, parse_dt, read_json, utcnow

ARCHIVE_DIR = DATA / "validation" / "archive" / "submitted"
LOCKED = CONFIG / "locked_squad.json"
MANUAL_LINEUP = CONFIG / "manual_lineup.json"


def submitted_state_path(gw: int) -> Path:
    return ARCHIVE_DIR / f"gw{int(gw):02d}.json"


def _digest(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _official_core(picks: dict) -> dict:
    rows = list(picks.get("picks") or [])
    if len(rows) != 15:
        raise RuntimeError(f"Official submitted picks must contain 15 players, got {len(rows)}")
    normalized = sorted(
        (
            {
                "element": int(row["element"]),
                "position": int(row["position"]),
                "multiplier": int(row.get("multiplier") or 0),
                "captain": bool(row.get("is_captain")),
                "vice_captain": bool(row.get("is_vice_captain")),
            }
            for row in rows
        ),
        key=lambda row: row["position"],
    )
    positions = [row["position"] for row in normalized]
    if positions != list(range(1, 16)):
        raise RuntimeError(f"Official submitted pick positions invalid: {positions}")
    captains = [row for row in normalized if row["captain"]]
    vice = [row for row in normalized if row["vice_captain"]]
    if len(captains) != 1 or len(vice) != 1:
        raise RuntimeError("Official submitted picks must contain exactly one captain and vice-captain")
    return {
        "players": normalized,
        "squad_elements": [row["element"] for row in normalized],
        "starting_xi": [row["element"] for row in normalized[:11]],
        "bench": [row["element"] for row in normalized[11:]],
        "captain": captains[0]["element"],
        "vice_captain": vice[0]["element"],
        "active_chip": picks.get("active_chip"),
        "entry_history": picks.get("entry_history") or {},
    }


def _baseline_for_gw(gw: int) -> dict:
    locked = read_json(LOCKED, {})
    manual = read_json(MANUAL_LINEUP, {})
    target = int(locked.get("target_gw") or 0) or None
    applicable = target == int(gw)
    squad = [int(row["element"]) for row in (locked.get("players") or []) if row.get("element") is not None] if applicable else []
    starting = [int(row["element"]) for row in (manual.get("starting_xi") or []) if isinstance(row, dict) and row.get("element") is not None] if applicable else []
    bench = [int(row["element"]) for row in (manual.get("bench") or []) if isinstance(row, dict) and row.get("element") is not None] if applicable else []
    captain = (manual.get("captain") or {}).get("element") if isinstance(manual.get("captain"), dict) else manual.get("captain")
    vice = (manual.get("vice_captain") or {}).get("element") if isinstance(manual.get("vice_captain"), dict) else manual.get("vice_captain")
    return {
        "applicable": applicable,
        "target_gw": target,
        "squad_elements": squad,
        "starting_xi": starting,
        "bench": bench,
        "captain": int(captain) if applicable and captain is not None else None,
        "vice_captain": int(vice) if applicable and vice is not None else None,
        "chip": manual.get("active_chip") if applicable else None,
        "source": "locked_squad+manual_lineup" if applicable else "NOT_APPLICABLE_TARGET_GW_MISMATCH",
    }


def _comparison(baseline: dict, official: dict) -> dict:
    if not baseline.get("applicable"):
        return {"status": "BASELINE_NOT_APPLICABLE", "material_change": None}
    baseline_squad = set(baseline.get("squad_elements") or [])
    official_squad = set(official.get("squad_elements") or [])
    return {
        "status": "COMPARED",
        "squad_added": sorted(official_squad - baseline_squad),
        "squad_removed": sorted(baseline_squad - official_squad),
        "starting_xi_changed": bool(baseline.get("starting_xi")) and baseline.get("starting_xi") != official.get("starting_xi"),
        "bench_changed": bool(baseline.get("bench")) and baseline.get("bench") != official.get("bench"),
        "captain_changed": baseline.get("captain") is not None and baseline.get("captain") != official.get("captain"),
        "vice_captain_changed": baseline.get("vice_captain") is not None and baseline.get("vice_captain") != official.get("vice_captain"),
        "chip_changed": baseline.get("chip") is not None and baseline.get("chip") != official.get("active_chip"),
        "material_change": bool((official_squad - baseline_squad) or (baseline_squad - official_squad)),
    }


def submitted_state_integrity(payload: dict, expected_gw: int | None = None) -> tuple[bool, str | None]:
    if not payload or payload.get("kind") != "official_submitted_state":
        return False, "wrong_kind"
    if payload.get("immutable") is not True or payload.get("official_truth") is not True:
        return False, "not_immutable_official_truth"
    if expected_gw is not None and int(payload.get("gw") or -1) != int(expected_gw):
        return False, "gw_mismatch"
    official = payload.get("submitted") or {}
    if len(official.get("players") or []) != 15 or len(official.get("starting_xi") or []) != 11 or len(official.get("bench") or []) != 4:
        return False, "submitted_shape_invalid"
    if official.get("captain") is None or official.get("vice_captain") is None:
        return False, "captaincy_missing"
    if payload.get("submitted_sha256") != _digest(official):
        return False, "submitted_digest_mismatch"
    deadline = parse_dt(payload.get("deadline_time"))
    captured = parse_dt(payload.get("captured_at"))
    if not deadline or not captured or deadline.tzinfo is None or captured.tzinfo is None or captured < deadline:
        return False, "timestamp_invalid"
    return True, None


def persist_submitted_state(gw: int, deadline_time: str, picks: dict, now: datetime | None = None) -> dict:
    deadline = parse_dt(deadline_time)
    current = now or utcnow()
    if not deadline or deadline.tzinfo is None or current.tzinfo is None:
        raise RuntimeError("submitted state requires timezone-aware deadline and capture time")
    if current < deadline:
        raise RuntimeError("pre-deadline submitted state archive rejected")
    official = _official_core(picks)
    path = submitted_state_path(gw)
    existing = read_json(path, None)
    if existing:
        ok, reason = submitted_state_integrity(existing, gw)
        if not ok:
            raise RuntimeError(f"existing submitted state failed integrity: {reason}")
        if existing.get("submitted_sha256") != _digest(official):
            raise RuntimeError("immutable submitted state conflicts with later Official payload")
        return existing
    baseline = _baseline_for_gw(gw)
    payload = {
        "schema_version": 4963,
        "kind": "official_submitted_state",
        "gw": int(gw),
        "deadline_time": deadline_time,
        "captured_at": current.isoformat(),
        "official_truth": True,
        "immutable": True,
        "submitted": official,
        "submitted_sha256": _digest(official),
        "predeadline_baseline": baseline,
        "baseline_comparison": _comparison(baseline, official),
        "guardrails": {
            "official_picks_only": True,
            "exactly_15_players": True,
            "starting_xi_from_official_pick_positions_1_to_11": True,
            "bench_order_from_official_pick_positions_12_to_15": True,
            "captain_vice_from_official_flags": True,
            "chip_from_official_picks": True,
            "archive_append_only": True,
            "later_conflicting_payload_fails_closed": True,
        },
    }
    ok, reason = submitted_state_integrity(payload, gw)
    if not ok:
        raise RuntimeError(f"submitted state failed integrity before write: {reason}")
    atomic_json(path, payload)
    return payload
