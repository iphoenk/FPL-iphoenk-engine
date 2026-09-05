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


def test_partial_picks_never_claim_all_managers_collected():
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
    elements = {100: {"web_name": "Example", "club": "AAA", "position": "MID"}}

    artifact = exposure_artifact(
        manager_picks,
        elements,
        bootstrap_lineage=None,
    )

    assert artifact["expected_manager_count"] == 2
    assert artifact["collected_manager_count"] == 1
    assert artifact["submitted_picks_available_count"] == 1
    assert artifact["submitted_picks_missing_count"] == 1
    assert artifact["coverage_percent"] == 50.0
    assert artifact["health"] == "AMBER"
    assert artifact["complete"] is False
    assert artifact["ownership_denominator"] == 1
    assert artifact["players"][0]["ownership_percent"] == 100.0


def test_complete_mini_league_exposure_is_green_only_at_full_coverage():
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
    elements = {100: {"web_name": "Example", "club": "AAA", "position": "MID"}}

    artifact = exposure_artifact(
        manager_picks,
        elements,
        bootstrap_lineage=None,
    )

    assert artifact["collected_manager_count"] == 2
    assert artifact["submitted_picks_missing_count"] == 0
    assert artifact["coverage_percent"] == 100.0
    assert artifact["health"] == "GREEN"
    assert artifact["complete"] is True


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
