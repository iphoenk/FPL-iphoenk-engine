from __future__ import annotations

from src.runtime_v6.league_prefetch import exposure_artifact


def _available(entry_id: int, element_id: int) -> dict:
    return {
        "entry_id": entry_id,
        "status": "AVAILABLE",
        "picks": [
            {
                "element_id": element_id,
                "squad_position": 1,
                "multiplier": 1,
                "captain": False,
                "vice_captain": False,
            }
        ],
    }


def test_partial_picks_integrity_metadata_never_claims_full_coverage():
    manager_picks = {
        "season": "2026-2027",
        "gw": 3,
        "league_id": 9477,
        "expected_manager_count": 2,
        "entries": {
            "1": _available(1, 100),
            "2": {"entry_id": 2, "status": "UNAVAILABLE", "picks": []},
        },
        "lineage": {},
    }

    artifact = exposure_artifact(manager_picks, {}, bootstrap_lineage=None)

    assert artifact["expected_manager_count"] == 2
    assert artifact["collected_manager_count"] == 1
    assert artifact["submitted_picks_available_count"] == 1
    assert artifact["submitted_picks_missing_count"] == 1
    assert artifact["coverage_percent"] == 50.0
    assert artifact["health"] == "AMBER"
    assert artifact["complete"] is False
    assert artifact["deprecated"] is True
    assert artifact["canonical"] is False
    assert artifact["analytics_removed"] is True
    assert artifact["players"] == []


def test_complete_mini_league_integrity_metadata_is_green_only_at_full_coverage():
    manager_picks = {
        "season": "2026-2027",
        "gw": 3,
        "league_id": 9477,
        "expected_manager_count": 2,
        "entries": {
            "1": _available(1, 100),
            "2": _available(2, 100),
        },
        "lineage": {},
    }

    artifact = exposure_artifact(manager_picks, {}, bootstrap_lineage=None)

    assert artifact["collected_manager_count"] == 2
    assert artifact["submitted_picks_missing_count"] == 0
    assert artifact["coverage_percent"] == 100.0
    assert artifact["health"] == "GREEN"
    assert artifact["complete"] is True
    assert artifact["players"] == []


def test_zero_available_managers_is_red_not_false_complete():
    manager_picks = {
        "season": "2026-2027",
        "gw": 3,
        "league_id": 9477,
        "expected_manager_count": 1,
        "entries": {"1": {"entry_id": 1, "status": "UNAVAILABLE", "picks": []}},
        "lineage": {},
    }

    artifact = exposure_artifact(manager_picks, {}, bootstrap_lineage=None)

    assert artifact["collected_manager_count"] == 0
    assert artifact["coverage_percent"] == 0.0
    assert artifact["health"] == "RED"
    assert artifact["complete"] is False
    assert artifact["players"] == []
