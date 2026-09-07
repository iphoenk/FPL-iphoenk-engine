from __future__ import annotations

from src.runtime_v6.league_prefetch import acquire_manager_picks


class FakeClient:
    def __init__(self, available_ids: set[int]) -> None:
        self.available_ids = available_ids

    def submitted_picks(self, entry_id: int, gw: int) -> dict:
        if entry_id not in self.available_ids:
            return {
                "status": "UNAVAILABLE",
                "checked_at": "2026-09-07T00:00:00+00:00",
                "http_status": 404,
                "payload": {},
            }
        return {
            "status": "LIVE",
            "checked_at": "2026-09-07T00:00:00+00:00",
            "http_status": 200,
            "payload": {
                "active_chip": None,
                "picks": [
                    {
                        "element": 100,
                        "position": 1,
                        "multiplier": 1,
                        "is_captain": False,
                        "is_vice_captain": False,
                    }
                ],
            },
        }


def _acquire(tmp_path, *, manager_ids: list[int], available_ids: set[int]) -> dict:
    artifact, _ = acquire_manager_picks(
        FakeClient(available_ids),
        previous_path=tmp_path / "previous.json",
        season="2026-2027",
        league_id=9477,
        gw=3,
        manager_ids=manager_ids,
        deadline_passed=True,
        workers=2,
        force=False,
        cache_enabled=False,
    )
    return artifact


def test_partial_picks_integrity_metadata_never_claims_full_coverage(tmp_path):
    artifact = _acquire(tmp_path, manager_ids=[1, 2], available_ids={1})

    assert artifact["expected_manager_count"] == 2
    assert artifact["collected_manager_count"] == 1
    assert artifact["submitted_picks_available_count"] == 1
    assert artifact["submitted_picks_missing_count"] == 1
    assert artifact["coverage_percent"] == 50.0
    assert artifact["health"] == "AMBER"
    assert artifact["complete"] is False


def test_complete_mini_league_integrity_metadata_is_green_only_at_full_coverage(tmp_path):
    artifact = _acquire(tmp_path, manager_ids=[1, 2], available_ids={1, 2})

    assert artifact["collected_manager_count"] == 2
    assert artifact["submitted_picks_missing_count"] == 0
    assert artifact["coverage_percent"] == 100.0
    assert artifact["health"] == "GREEN"
    assert artifact["complete"] is True


def test_zero_available_managers_is_red_not_false_complete(tmp_path):
    artifact = _acquire(tmp_path, manager_ids=[1], available_ids=set())

    assert artifact["collected_manager_count"] == 0
    assert artifact["coverage_percent"] == 0.0
    assert artifact["health"] == "RED"
    assert artifact["complete"] is False
