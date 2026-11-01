"""O1 point-in-time CURRENT15 evidence helpers (Phase E, 2026-11-01).

Two read-only capabilities, both fail-closed:

* ``collect_archive_candidates`` reads the private ``personal/snapshots/``
  archive inside explicit bounds (cutoff, look-back window, file count) so a
  valid snapshot that existed before the source cutoff can be selected even
  though the mutable ``personal/current_team.json`` was overwritten later.
* ``reconstruct_public_current15`` rebuilds OUR15 from the previous finished
  GW's Official picks plus public Official transfers with timestamps up to the
  cutoff.  The result is ``PUBLIC_INFERRED``: never authenticated-current, with
  no bank, free-transfer, purchase- or selling-price values.

Nothing here writes to any snapshot, report or historical artifact.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SNAPSHOT_NAME = re.compile(
    r"^current_team_(\d{4}-\d{2}-\d{2})T(\d{2})(\d{2})(\d{2})\.(\d{6})_plus_0000\.json$"
)
DEFAULT_MAX_ARCHIVE_FILES = 64
DEFAULT_ARCHIVE_LOOKBACK = timedelta(hours=96)
POSITION_NAMES = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
POSITION_QUOTA = {1: 2, 2: 5, 3: 5, 4: 3}
MAX_PER_CLUB = 3
SOURCE_CLASS = "PUBLIC_INFERRED_RECONSTRUCTION"


def aware_utc(value: Any) -> datetime | None:
    """Parse an ISO timestamp; naive or invalid values return ``None``."""
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def parse_snapshot_filename_ts(name: str) -> datetime | None:
    match = SNAPSHOT_NAME.match(str(name or ""))
    if not match:
        return None
    day, hh, mm, ss, micro = match.groups()
    try:
        return datetime.fromisoformat(f"{day}T{hh}:{mm}:{ss}.{micro}+00:00")
    except ValueError:
        return None


def collect_archive_candidates(
    snapshots_dir: Path,
    *,
    cutoff: datetime | None,
    max_files: int = DEFAULT_MAX_ARCHIVE_FILES,
    lookback: timedelta = DEFAULT_ARCHIVE_LOOKBACK,
    source_prefix: str = "PRIVATE:personal/snapshots/",
) -> list[dict[str, Any]]:
    """Bounded read of archived authenticated snapshots (newest first).

    A snapshot is only returned when both its filename timestamp and its own
    ``generated_at`` are valid, agree (within 2 s), and are not after
    ``cutoff`` (future evidence).  Reading is bounded by ``max_files`` and
    ``lookback`` so a large archive can never stall a report run.
    """
    directory = Path(snapshots_dir)
    if not directory.is_dir():
        return []
    dated: list[tuple[datetime, str]] = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                ts = parse_snapshot_filename_ts(entry.name)
                if ts is None or not entry.is_file():
                    continue
                if cutoff is not None and (ts > cutoff or ts < cutoff - lookback):
                    continue
                dated.append((ts, entry.name))
    except OSError:
        return []
    dated.sort(reverse=True)
    out: list[dict[str, Any]] = []
    for ts, name in dated[: max(0, int(max_files))]:
        try:
            payload = json.loads((directory / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, Mapping) or not payload:
            continue
        generated = aware_utc(payload.get("generated_at"))
        if generated is None or abs((generated - ts).total_seconds()) > 2:
            continue
        if cutoff is not None and generated > cutoff:
            continue
        out.append(
            {
                "source": f"{source_prefix}{name}",
                "source_class": "AUTHENTICATED_CURRENT_TEAM",
                "payload": dict(payload),
                "observed_at": payload.get("generated_at"),
                "gw": payload.get("gw"),
                "auth_state": payload.get("auth_state"),
                "archive": True,
            }
        )
    return out


def _element(row: Mapping[str, Any]) -> int:
    try:
        return int(row.get("element_id") or row.get("element") or 0)
    except (TypeError, ValueError):
        return 0


def _unavailable(reasons: list[str], cutoff: datetime | None) -> dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "reasons": list(dict.fromkeys(reasons)),
        "rows": [],
        "cutoff": cutoff.isoformat() if cutoff else None,
        "auth_state": "UNAVAILABLE",
        "finance_allowed": False,
        "source_class": SOURCE_CLASS,
    }


def reconstruct_public_current15(
    *,
    base_picks: Sequence[Mapping[str, Any]],
    transfers: Sequence[Mapping[str, Any]],
    planning_gw: int,
    cutoff: datetime,
    element_meta: Mapping[Any, Mapping[str, Any]],
    expected_entry_id: int | None = None,
    chip_in_planning_gw: str | None = None,
    expected_transfer_count: int | None = None,
    base_gw: int | None = None,
) -> dict[str, Any]:
    """Rebuild OUR15 at ``cutoff`` from public Official facts; fail closed."""
    cutoff = aware_utc(cutoff)
    if cutoff is None:
        return _unavailable(["CUTOFF_INVALID"], None)
    meta = {int(k): dict(v) for k, v in element_meta.items()}
    reasons: list[str] = []

    if str(chip_in_planning_gw or "").strip().lower() in {"freehit", "free_hit"}:
        reasons.append("CHIP_FREEHIT_SQUAD_NOT_DERIVABLE_FROM_TRANSFERS")

    base_ids = [_element(row) for row in base_picks]
    if len(base_ids) != 15 or len(set(base_ids)) != 15 or 0 in base_ids:
        reasons.append(f"BASE_PICKS_NOT_15_UNIQUE:{len(base_ids)}")
    squad: dict[int, dict[str, Any]] = {}
    for row in base_picks:
        eid = _element(row)
        if eid <= 0:
            continue
        squad[eid] = {
            "element_id": eid,
            "provenance": f"BASE_PICKS_GW{base_gw if base_gw is not None else int(planning_gw) - 1}",
            "squad_position": row.get("squad_position", row.get("position")),
        }

    applied: list[dict[str, Any]] = []
    for transfer in transfers:
        if not isinstance(transfer, Mapping):
            reasons.append("TRANSFER_ROW_INVALID")
            continue
        if expected_entry_id is not None and str(transfer.get("entry")) != str(expected_entry_id):
            reasons.append("TRANSFER_ENTRY_MISMATCH")
            continue
        try:
            event = int(transfer.get("event"))
        except (TypeError, ValueError):
            reasons.append("TRANSFER_EVENT_INVALID")
            continue
        if event != int(planning_gw):
            continue
        when = aware_utc(transfer.get("time"))
        if when is None:
            reasons.append("TRANSFER_TIMESTAMP_INVALID")
            continue
        if when > cutoff:
            continue  # future relative to the cutoff: must not be known yet
        applied.append({**dict(transfer), "_when": when})
    applied.sort(key=lambda row: row["_when"])

    for transfer in applied:
        out_id, in_id = int(transfer.get("element_out") or 0), int(transfer.get("element_in") or 0)
        if out_id not in squad:
            reasons.append(f"TRANSFER_OUT_NOT_IN_SQUAD:{out_id}")
            continue
        if in_id in squad:
            reasons.append(f"TRANSFER_IN_ALREADY_OWNED:{in_id}")
            continue
        if out_id not in meta or in_id not in meta:
            reasons.append(f"ELEMENT_UNKNOWN:{out_id}/{in_id}")
            continue
        if meta[out_id].get("element_type") != meta[in_id].get("element_type"):
            reasons.append(f"POSITION_MISMATCH:{out_id}/{in_id}")
            continue
        slot = squad.pop(out_id)
        squad[in_id] = {
            "element_id": in_id,
            "provenance": f"TRANSFER_IN:{transfer['_when'].isoformat()}",
            "squad_position": slot.get("squad_position"),
        }

    if expected_transfer_count is not None and int(expected_transfer_count) != len(applied):
        reasons.append(f"TRANSFER_COUNT_MISMATCH:expected={expected_transfer_count},observed={len(applied)}")

    if len(squad) != 15:
        reasons.append(f"SQUAD_NOT_15:{len(squad)}")
    else:
        unknown = [eid for eid in squad if eid not in meta]
        if unknown:
            reasons.append(f"ELEMENT_UNKNOWN:{sorted(unknown)}")
        else:
            counts: dict[int, int] = {}
            clubs: dict[int, int] = {}
            for eid in squad:
                counts[int(meta[eid]["element_type"])] = counts.get(int(meta[eid]["element_type"]), 0) + 1
                clubs[int(meta[eid]["team"])] = clubs.get(int(meta[eid]["team"]), 0) + 1
            if counts != POSITION_QUOTA:
                reasons.append(f"POSITION_QUOTA_VIOLATION:{counts}")
            if any(n > MAX_PER_CLUB for n in clubs.values()):
                reasons.append("CLUB_LIMIT_EXCEEDED")

    if reasons:
        return _unavailable(reasons, cutoff)

    rows = []
    for eid, info in sorted(squad.items(), key=lambda kv: (kv[1].get("squad_position") or 99, kv[0])):
        rows.append(
            {
                "element_id": eid,
                "element": eid,
                "position": POSITION_NAMES[int(meta[eid]["element_type"])],
                "team_id": int(meta[eid]["team"]),
                "squad_position": info.get("squad_position"),
                "provenance": info["provenance"],
                "purchase_price": None,
                "selling_price": None,
                "sell_value": None,
            }
        )
    return {
        "status": "PUBLIC_INFERRED",
        "reasons": [],
        "rows": rows,
        "cutoff": cutoff.isoformat(),
        "auth_state": "PUBLIC_INFERRED",
        "finance_allowed": False,
        "source_class": SOURCE_CLASS,
        "transfers_applied": len(applied),
        "base_gw": base_gw if base_gw is not None else int(planning_gw) - 1,
    }
