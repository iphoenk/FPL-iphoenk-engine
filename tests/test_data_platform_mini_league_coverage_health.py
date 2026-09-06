from __future__ import annotations

from pathlib import Path

from src.runtime_v6.league_prefetch import acquire_manager_picks


def _result(entry_id: int, *, available: bool) -> dict:
    if not available:
        return {
            "status": "FAILED",
            "endpoint_class": "submitted_picks",
            "checked_at": "2026-09-06T16:00:00+00:00",
            "http_status": 503,
            "payload_digest": None,
            "payload": None,
        }
    return {
        "status": "LIVE",
        "endpoint_class": "submitted_picks",
        "checked_at": "2026-09-06T16:00:00+00:00",
        "http_status": 200,
        "payload_digest": f"digest-{entry_id}",
        "payload": {
            "active_chip": None,
            "picks": [
                {
                    "element": 100 + entry_id,
                    "position": 1,
                    "multiplier": 1,
                    "is_captain": False,
                    "is_vice_captain": False,
                }
            ],
        },
    }


class PicksClient:
    def __init__(self, availability: dict[int, bool]) -> None:
        self.availability = availability

    def submitted_picks(self, entry_id: int, gw: int) -> dict:
        del gw
        return _result(entry_id, available=self.availability.get(entry_id, False))


def _collect(tmp_path: Path, availability: dict[int, bool]) -> dict:
    manager_ids = sorted(availability)
    artifact, _ = acquire_manager_picks(
        PicksClient(availability),
        previous_path=tmp_path / "gw_3_manager_picks.json",
        season="2026-2027",
        league_id=9477,
        gw=3,
        manager_ids=manager_ids,
        deadline_passed=True,
        workers=4,
        force=False,
        cache_enabled=False,
    )
    return artifact


def test_partial_picks_integrity_metadata_never_claims_full_coverage(tmp_path: Path):
    artifact = _collect(tmp_path, {1: True, 2: False})

    assert artifact["expected_manager_count"] == 2
    assert artifact["collected_manager_count"] == 1
    assert artifact["submitted_picks_available_count"] == 1
    assert artifact["submitted_picks_missing_count"] == 1
    assert artifact["coverage_percent"] == 50.0
    assert artifact["health"] == "AMBER"
    assert artifact["complete"] is False
    assert artifact["authority"] == "OFFICIAL_FPL"
    assert artifact["governance"]["mini_league_analytics_authority"] == "NONE"
    assert "players" not in artifact


def test_complete_mini_league_integrity_metadata_is_green_only_at_full_coverage(tmp_path: Path):
    artifact = _collect(tmp_path, {1: True, 2: True})

    assert artifact["collected_manager_count"] == 2
    assert artifact["submitted_picks_missing_count"] == 0
    assert artifact["coverage_percent"] == 100.0
    assert artifact["health"] == "GREEN"
    assert artifact["complete"] is True
    assert artifact["cache"]["current_run_action"] == "FETCHED"
    assert "players" not in artifact


def test_zero_available_managers_is_red_not_false_complete(tmp_path: Path):
    artifact = _collect(tmp_path, {1: False})

    assert artifact["collected_manager_count"] == 0
    assert artifact["submitted_picks_missing_count"] == 1
    assert artifact["coverage_percent"] == 0.0
    assert artifact["health"] == "RED"
    assert artifact["complete"] is False
    assert artifact["missing_entry_ids"] == [1]
    assert "players" not in artifact
