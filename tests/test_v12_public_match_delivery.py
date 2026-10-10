from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.engines.v12_public_match_delivery import (
    PublicMatchError,
    _exposure,
    _validated_inputs,
)


SLOT = "2026-10-10T20:57:00+07:00"
CHECKED = "2026-10-10T13:57:15+00:00"


def _write(root: Path, name: str, payload: dict) -> None:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(tmp_path: Path, *, gw: int = 6) -> None:
    root = tmp_path / "data/v6"
    _write(root, "report_prefetch/latest.json", {
        "report_kind": "match_mode",
        "target_logical_report_slot": SLOT,
        "public_core_complete": True,
        "live_requested": True,
        "mini_league_requested": True,
        "gw": gw,
        "entry_id": 3462711,
        "priority_league_id": 9477,
        "generated_at": CHECKED,
    })
    picks = [
        {
            "element_id": i,
            "squad_position": i,
            "multiplier": 2 if i == 7 else (1 if i <= 11 else 0),
            "captain": i == 7,
            "vice_captain": i == 8,
        }
        for i in range(1, 16)
    ]
    entries = {
        str(3462711 if i == 1 else i + 5000000): {"picks": picks}
        for i in range(1, 59)
    }
    _write(root, f"mini_leagues/9477/gw_{gw}_manager_picks.json", {
        "gw": gw, "complete": True, "expected_manager_count": 58,
        "submitted_picks_available_count": 58, "entries": entries,
    })
    _write(root, "mini_leagues/9477/standings.json", {
        "managers": [
            {"entry_id": int(x), "league_rank": i, "manager_name": f"Manager {i}"}
            for i, x in enumerate(entries, start=1)
        ],
        "league_name": "ICON+ League",
    })
    _write(root, "mini_leagues/9477/live_state.json", {
        "gw": gw, "status": "AVAILABLE", "authority": "OFFICIAL_FPL",
        "checked_at": CHECKED,
        "elements": [{"element_id": i, "total_points": i, "minutes": 90} for i in range(1, 16)],
    })


def test_match_public_is_independent_of_expired_private_auth(tmp_path: Path) -> None:
    _fixture(tmp_path)
    # The private tree and session credentials do not exist.
    gw, entry, _, picks, standings, live = _validated_inputs(tmp_path, SLOT)
    assert gw == 6
    assert entry == 3462711
    assert len(picks["entries"]) == len(standings["managers"]) == 58
    assert live["status"] == "AVAILABLE"


def test_match_public_rejects_cross_occurrence_stale_reuse(tmp_path: Path) -> None:
    _fixture(tmp_path)
    with pytest.raises(PublicMatchError, match="MATCH_PREFETCH_OCCURRENCE_MISMATCH"):
        _validated_inputs(tmp_path, "2026-10-10T21:10:00+07:00")


def test_match_public_58_scoring_multipliers_and_eo_not_ownership(tmp_path: Path) -> None:
    _fixture(tmp_path)
    _, entry, _, members, standings, live = _validated_inputs(tmp_path, SLOT)
    icon = _exposure(members, live, standings, entry, {i: f"Player {i}" for i in range(1, 16)})
    row = next(r for r in icon["material_player_exposure"] if r["player"] == "Player 7")
    assert row["owned"] == {"numerator": 58, "denominator": 58, "percentage": 100.0}
    assert row["captain"] == {"numerator": 58, "denominator": 58, "percentage": 100.0}
    assert row["eo"] == {"numerator": 116, "denominator": 58, "percentage": 200.0}
    assert icon["live_standings_rank"]["state"] == "UNAVAILABLE"
    assert icon["current_live_rank"] is None


def test_match_public_fail_closed_on_missing_manager_picks(tmp_path: Path) -> None:
    _fixture(tmp_path)
    root = tmp_path / "data/v6"
    file = root / "mini_leagues/9477/gw_6_manager_picks.json"
    payload = json.loads(file.read_text())
    payload["entries"].pop(next(iter(payload["entries"])))
    file.write_text(json.dumps(payload))
    with pytest.raises(PublicMatchError, match="MATCH_PUBLIC_58_OR_LIVE_INCOMPLETE"):
        _validated_inputs(tmp_path, SLOT)
