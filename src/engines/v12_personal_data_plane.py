from __future__ import annotations

"""P1 private personal-data input boundary.

This module only assembles evidence candidates. The existing V12 personal
selection function remains the semantic authority. No scoring, ranking, lineup,
captain, transfer, or Stage3 mathematics lives here.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


class PersonalDataPlaneError(RuntimeError):
    pass


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file() or path.stat().st_size <= 0:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _confirmed_candidate(
    confirmed: Mapping[str, Any] | None,
    *,
    source: str,
) -> dict[str, Any] | None:
    confirmed = dict(confirmed or {})
    explicit_at = (
        confirmed.get("explicit_user_confirmed_at")
        or confirmed.get("evidence_timestamp")
        or confirmed.get("confirmed_at")
    )
    explicit_gw = (
        confirmed.get("applicable_planning_gw")
        or confirmed.get("planning_gw")
        or confirmed.get("gw")
    )
    explicit_flag = confirmed.get("explicit_user_confirmation") is True
    if not (explicit_at and explicit_gw is not None and explicit_flag):
        return None

    players: list[dict[str, Any]] = []
    for group, position in (
        ("goalkeepers", "GK"),
        ("defenders", "DEF"),
        ("midfielders", "MID"),
        ("forwards", "FWD"),
    ):
        for item in confirmed.get(group) or []:
            if not isinstance(item, Mapping):
                continue
            element = item.get("element_id", item.get("element"))
            if element is None:
                continue
            players.append(
                {
                    **dict(item),
                    "element_id": int(element),
                    "position": position,
                }
            )

    return {
        "source": source,
        "source_class": "USER_CONFIRMED",
        "payload": {
            "players": players,
            "generated_at": explicit_at,
            "gw": explicit_gw,
            "bank": confirmed.get("bank"),
            "free_transfers": confirmed.get("free_transfers"),
            "hit_cost_per_extra_transfer": confirmed.get("hit_cost_per_extra_transfer"),
            "current_transfer_cost_points": confirmed.get("current_transfer_cost_points"),
            "chips": confirmed.get("chips"),
            "availability": confirmed.get("availability") or {},
        },
        "observed_at": explicit_at,
        "gw": explicit_gw,
        "auth_state": "USER_CONFIRMED",
        "applicable_planning_gw": int(explicit_gw),
        "explicit_confirmation": True,
    }


def _current_team_candidates(
    directory: Path,
    *,
    source_prefix: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*current_team*.json")):
        payload = _read_json(path, {}) or {}
        if not isinstance(payload, Mapping) or not payload:
            continue
        out.append(
            {
                "source": f"{source_prefix}{path.name}",
                "source_class": "AUTHENTICATED_CURRENT_TEAM",
                "payload": dict(payload),
                "observed_at": payload.get("generated_at"),
                "gw": payload.get("gw"),
                "auth_state": payload.get("auth_state"),
            }
        )
    return out


def _manual_capture_candidates(
    directory: Path,
    *,
    source_prefix: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        payload = _read_json(path, {}) or {}
        if not isinstance(payload, Mapping):
            continue
        if payload.get("schema") != "FPL_MANUAL_CURRENT_TEAM_CAPTURE_V1":
            continue
        squad = [
            dict(row)
            for row in payload.get("squad") or []
            if isinstance(row, Mapping)
        ]
        finance = dict(payload.get("finance") or {})
        chips = dict(payload.get("chips") or {})
        current_payload = {
            "players": squad,
            "generated_at": payload.get("captured_at"),
            "gw": payload.get("planning_gw"),
            "bank": finance.get("bank"),
            "free_transfers": finance.get("free_transfers"),
            "current_transfer_cost_points": finance.get(
                "current_transfer_cost_points"
            ),
            "hit_cost_per_extra_transfer": finance.get(
                "hit_cost_per_extra_transfer"
            ),
            "chips": chips,
            "availability": {
                "bank": (
                    "AVAILABLE"
                    if isinstance(finance.get("bank"), int)
                    else "UNAVAILABLE"
                ),
                "free_transfers": (
                    "AVAILABLE"
                    if isinstance(finance.get("free_transfers"), int)
                    else "UNAVAILABLE"
                ),
                "purchase_price": "UNAVAILABLE",
                "selling_price": "UNAVAILABLE",
                "chips": "PARTIAL_CAPTURE" if chips else "UNAVAILABLE",
            },
            "auth_state": "USER_CONFIRMED",
        }
        out.append(
            {
                "source": f"{source_prefix}{path.name}",
                "source_class": "USER_CONFIRMED",
                "payload": current_payload,
                "observed_at": payload.get("captured_at"),
                "gw": payload.get("planning_gw"),
                "auth_state": "USER_CONFIRMED",
                "applicable_planning_gw": payload.get("planning_gw"),
                "explicit_confirmation": True,
            }
        )
    return out


def collect_personal_evidence_candidates(
    *,
    runtime_root: Path,
    legacy_state: Mapping[str, Any] | None,
    planning_gw: int,
    private_root: Path | None = None,
    allow_legacy_private_sources: bool = True,
    require_private_personal: bool = False,
    enforce_public_disclosure: bool = True,
) -> list[dict[str, Any]]:
    """Assemble inputs while keeping V12 selection semantics external.

    Public submitted picks are admitted only when their GW is strictly before
    the planning GW, which establishes that the picks belong to an already
    disclosed deadline state rather than a current private decision.
    """
    candidates: list[dict[str, Any]] = []

    if private_root is not None:
        private_personal = private_root / "personal"
        candidates.extend(
            _current_team_candidates(
                private_personal,
                source_prefix="PRIVATE:personal/",
            )
        )
        candidates.extend(
            _manual_capture_candidates(
                private_personal / "manual",
                source_prefix="PRIVATE:personal/manual/",
            )
        )
        private_owner_state = _read_json(
            private_personal / "owner_state.json", {}
        ) or {}
        candidate = _confirmed_candidate(
            (private_owner_state or {}).get("confirmed_current_squad_state"),
            source="PRIVATE:personal/owner_state.json:EXPLICIT_USER_CONFIRMED",
        )
        if candidate is not None:
            candidates.append(candidate)

    private_candidate_count = len(candidates)
    if require_private_personal and private_candidate_count == 0:
        raise PersonalDataPlaneError(
            "private personal input required but no private current/manual state found"
        )

    if allow_legacy_private_sources:
        personal_dir = runtime_root / "data/v6/personal"
        candidates.extend(
            _current_team_candidates(
                personal_dir,
                source_prefix="data/v6/personal/",
            )
        )
        confirmed = dict(
            ((legacy_state or {}).get("confirmed_current_squad_state") or {})
        )
        candidate = _confirmed_candidate(
            confirmed,
            source="FPL_MASTER_STATE_V12:EXPLICIT_USER_CONFIRMED",
        )
        if candidate is not None:
            candidates.append(candidate)

    submitted_path = runtime_root / "data/v6/personal/submitted_picks.json"
    submitted = _read_json(submitted_path, {}) or {}
    if isinstance(submitted, Mapping) and submitted:
        try:
            submitted_gw = int(submitted.get("gw") or 0)
        except (TypeError, ValueError):
            submitted_gw = 0
        disclosed = 0 < submitted_gw < int(planning_gw)
        if (not enforce_public_disclosure) or disclosed:
            candidates.append(
                {
                    "source": "data/v6/personal/submitted_picks.json",
                    "source_class": "OFFICIAL_SUBMITTED_PICKS",
                    "payload": dict(submitted),
                    "observed_at": submitted.get("generated_at"),
                    "gw": submitted.get("gw"),
                    "auth_state": "PUBLIC_OFFICIAL",
                }
            )

    return candidates


def candidate_payload_fingerprint(candidates: list[dict[str, Any]]) -> str:
    """Fingerprint candidate semantics while ignoring storage-location labels."""
    normalized = []
    for row in candidates:
        normalized.append(
            {
                "source_class": row.get("source_class"),
                "payload": row.get("payload"),
                "observed_at": row.get("observed_at"),
                "gw": row.get("gw"),
                "auth_state": row.get("auth_state"),
                "applicable_planning_gw": row.get("applicable_planning_gw"),
                "explicit_confirmation": row.get("explicit_confirmation"),
            }
        )
    payload = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
