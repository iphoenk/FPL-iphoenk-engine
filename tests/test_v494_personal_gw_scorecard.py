from pathlib import Path

import pytest

from src.services.gw_scorecard_service import (
    archive_finished_gw,
    attach_squad_basis,
    build_actual_gw,
    build_planning_projection,
)


def _raw_finished() -> dict:
    return {
        "team_id": 1,
        "phase": {"submitted_gw": 1, "scoring_gw": 1},
        "official": {
            "bootstrap": {
                "events": [{"id": 1, "finished": True}],
                "teams": [{"id": 1, "name": "A"}],
                "elements": [
                    {"id": 1, "web_name": "Captain", "team": 1, "element_type": 3},
                    {"id": 2, "web_name": "Bench", "team": 1, "element_type": 2},
                    {"id": 3, "web_name": "Starter", "team": 1, "element_type": 4},
                ],
            },
            "picks": {
                "entry_history": {"event_transfers_cost": 4, "points": 13},
                "picks": [
                    {"element": 1, "position": 1, "multiplier": 2, "is_captain": True, "is_vice_captain": False},
                    {"element": 3, "position": 2, "multiplier": 1, "is_captain": False, "is_vice_captain": True},
                    {"element": 2, "position": 12, "multiplier": 1, "is_captain": False, "is_vice_captain": False},
                ],
            },
            "event_live": {
                "elements": [
                    {"id": 1, "stats": {"total_points": 5, "minutes": 90}},
                    {"id": 2, "stats": {"total_points": 4, "minutes": 90}},
                    {"id": 3, "stats": {"total_points": 3, "minutes": 90}},
                ]
            },
            "history": {
                "chips": [{"name": "bboost", "event": 1}],
                "current": [{"event": 1, "points": 13, "overall_rank": 100, "rank": 20, "points_on_bench": 4}],
            },
        },
    }


def _lineup(chip: str) -> dict:
    xi = [
        {"element": i, "name": f"P{i}", "position": "MID" if i > 1 else "GK", "xpts": 1.0}
        for i in range(1, 12)
    ]
    return {
        "formation": "3-4-3",
        "xi_xpts": 11.0,
        "starting_xi": xi,
        "captain": dict(xi[1]),
        "vice_captain": dict(xi[2]),
        "bench": {
            "gk": {"element": 12, "name": "B12", "position": "GK", "xpts": 1.0},
            "order": [
                {"slot": 1, "element": 13, "name": "B13", "position": "DEF", "xpts": 1.0},
                {"slot": 2, "element": 14, "name": "B14", "position": "MID", "xpts": 1.0},
                {"slot": 3, "element": 15, "name": "B15", "position": "FWD", "xpts": 1.0},
            ],
        },
        "chip_context": {"active_chip": chip},
    }


def test_finished_gw_points_chip_captain_and_bench_are_multiplier_aware():
    actual = build_actual_gw(_raw_finished(), 1)
    assert actual is not None
    assert actual["status"] == "FINAL"
    assert actual["chip"] == "BENCH_BOOST" and actual["chip_short"] == "BB"
    assert actual["gross_points"] == 17
    assert actual["hit"] == 4
    assert actual["net_points"] == 13
    assert actual["official_points_match"] is True
    assert actual["bench_raw_points"] == 4
    assert actual["bench_counted_points"] == 4
    assert actual["captain"]["counted_points"] == 10


def test_projection_applies_captain_and_chip_semantics_without_double_counting():
    wildcard = build_planning_projection(_lineup("WILDCARD"), 2)
    assert wildcard["estimated_points"] == 12.0
    assert wildcard["standard_captain_team_xpts"] == 12.0
    assert wildcard["bench_counted_xpts"] == 0

    bench_boost = build_planning_projection(_lineup("BENCH_BOOST"), 2)
    assert bench_boost["estimated_points"] == 16.0
    assert bench_boost["bench_counted_xpts"] == 4.0

    triple_captain = build_planning_projection(_lineup("TRIPLE_CAPTAIN"), 2)
    assert triple_captain["estimated_points"] == 13.0
    assert triple_captain["captain"]["multiplier"] == 3
    assert triple_captain["uncertainty"]["player_intervals_not_naively_summed"] is True


def test_projection_publishes_previous_gw_baseline_and_targeted_override():
    projection = build_planning_projection(_lineup("WILDCARD"), 2)
    raw = {
        "projection_baseline": {
            "planning_gw": 2,
            "baseline_gw": 1,
            "default_rule": "PLANNING_GW_FROM_PREVIOUS_OFFICIAL_SUBMITTED_SQUAD",
            "override_applied": True,
            "override_target_gw": 2,
            "effective_authority": "LOCKED_PRE_DEADLINE",
            "authority_source": "USER_CAPTURED_WC_DRAFT",
        }
    }
    scored = attach_squad_basis(projection, raw)
    assert scored["squad_basis"]["baseline_gw"] == 1
    assert scored["squad_basis"]["override_target_gw"] == 2
    assert scored["squad_basis"]["authority_source"] == "USER_CAPTURED_WC_DRAFT"


def test_projection_basis_must_match_planning_gw():
    projection = build_planning_projection(_lineup("NONE"), 3)
    with pytest.raises(RuntimeError, match="planning GW mismatch"):
        attach_squad_basis(projection, {"projection_baseline": {"planning_gw": 2, "baseline_gw": 1}})


def test_finished_archive_is_immutable_and_simulation_never_writes(tmp_path: Path):
    actual = build_actual_gw(_raw_finished(), 1)
    assert actual is not None

    simulated_dir = tmp_path / "simulated"
    _, action, consistent = archive_finished_gw(actual, simulated_dir, simulated=True)
    assert action == "SIMULATION_NOT_WRITTEN" and consistent is True
    assert not (simulated_dir / "gw01.json").exists()

    archive_dir = tmp_path / "archive"
    first, action, consistent = archive_finished_gw(actual, archive_dir, simulated=False)
    assert action == "CREATED" and consistent is True
    original = (archive_dir / "gw01.json").read_bytes()

    changed = dict(actual, net_points=99)
    preserved, action, consistent = archive_finished_gw(changed, archive_dir, simulated=False)
    assert action == "PRESERVED" and consistent is False
    assert preserved["net_points"] == first["net_points"] == 13
    assert (archive_dir / "gw01.json").read_bytes() == original
