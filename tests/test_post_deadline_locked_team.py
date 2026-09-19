from __future__ import annotations

from src.engines.post_deadline_locked_team import (
    build_post_deadline_locked_team_view,
    reconcile_owned_match_events,
)


def _current_team(*, generated_at: str = "2026-09-01T00:00:00+00:00") -> dict:
    positions = {
        1: "GK",
        2: "DEF", 3: "DEF", 4: "DEF",
        5: "MID", 6: "MID", 7: "MID", 8: "MID",
        9: "FWD", 10: "FWD", 11: "FWD",
        12: "GK", 13: "DEF", 14: "MID", 15: "FWD",
    }
    return {
        "canonical": True,
        "authority": "OFFICIAL_FPL",
        "auth_state": "AUTH_AVAILABLE",
        "squad_state": "AUTHENTICATED_CURRENT_TEAM",
        "gw": 5,
        "generated_at": generated_at,
        "lineage": {"authenticated": [{"source": "official_fpl"}]},
        "players": [
            {
                "element_id": eid,
                "position": positions[eid],
                "squad_position": eid,
                "multiplier": 2 if eid == 9 else (1 if eid <= 11 else 0),
                "captain": eid == 9,
                "vice_captain": eid == 5,
                "bench_order": eid - 11 if eid > 11 else None,
            }
            for eid in range(1, 16)
        ],
    }


def _locked(**kwargs) -> dict:
    return build_post_deadline_locked_team_view(
        _current_team(**kwargs),
        target_gw=5,
        deadline_passed=True,
    )


def _row(
    element: int,
    *,
    minutes: int,
    fixture_status: str = "FT",
    started: bool | None = None,
    points: int = 0,
    yellow: int = 0,
) -> dict:
    row = {
        "element": element,
        "fixture_status": fixture_status,
        "minutes": minutes,
        "total_points": points,
        "yellow_cards": yellow,
    }
    if started is not None:
        row["started_club_match"] = started
    return row


def test_a_starting_xi_dnp_activates_valid_bench_autosub():
    locked = _locked()
    result = reconcile_owned_match_events(
        locked,
        [
            _row(8, minutes=0),
            _row(12, minutes=0),
            _row(13, minutes=90, started=True, points=6),
        ],
    )
    player = next(row for row in result["players"] if row["element_id"] == 8)
    assert player["personal_state"] == "DNP_WITH_AUTOSUB_POSSIBLE"
    assert player["autosub"] == {"status": "ACTIVATES", "element_id": 13}


def test_b_starting_xi_late_cameo_blocks_autosub():
    locked = _locked()
    result = reconcile_owned_match_events(
        locked,
        [
            _row(8, minutes=21, started=False, points=1),
            _row(13, minutes=90, started=True, points=6),
        ],
    )
    player = next(row for row in result["players"] if row["element_id"] == 8)
    assert player["appearance_state"] == "CAMEO"
    assert player["personal_state"] == "CAMEO_BLOCKED_AUTOSUB"
    assert player["autosub"]["status"] == "BLOCKED_BY_APPEARANCE"


def test_c_cameo_plus_yellow_can_score_zero_and_still_blocks_autosub():
    locked = _locked()
    result = reconcile_owned_match_events(
        locked,
        [
            _row(8, minutes=21, started=False, points=0, yellow=1),
            _row(13, minutes=90, started=True, points=6),
        ],
    )
    player = next(row for row in result["players"] if row["element_id"] == 8)
    assert player["fpl_points"] == 0
    assert player["yellow_cards"] == 1
    assert player["personal_state"] == "CAMEO_BLOCKED_AUTOSUB"


def test_d_benched_player_dnp_does_not_activate_autosub_for_himself():
    result = reconcile_owned_match_events(_locked(), [_row(15, minutes=0)])
    player = result["players"][0]
    assert player["locked_role"] == "BENCH"
    assert player["personal_state"] == "BENCH_DNP_NO_DIRECT_XI_AUTOSUB_EFFECT"
    assert player["autosub"] is None


def test_e_authenticated_post_deadline_lineup_remains_immutable_despite_artifact_age():
    locked = _locked(generated_at="2026-08-01T00:00:00+00:00")
    assert locked["status"] == "CURRENT_IMMUTABLE"
    assert locked["freshness"]["artifact_age_can_stale_locked_fields"] is False
    assert len(locked["starting_xi"]) == 11
    assert len(locked["bench_order"]) == 4


def test_f_volatile_live_scope_can_degrade_without_staling_locked_xi():
    locked = build_post_deadline_locked_team_view(
        _current_team(),
        target_gw=5,
        deadline_passed=True,
        volatile_scope_status="DEGRADED_FRESHNESS",
    )
    assert locked["freshness"]["locked_lineup"] == "CURRENT_IMMUTABLE"
    assert locked["freshness"]["volatile_live_scope"] == "DEGRADED_FRESHNESS"
    assert locked["freshness"]["volatile_scope_is_independent"] is True


def test_g_completed_or_live_owned_players_are_all_reconciled():
    rows = [
        _row(2, minutes=90, started=True, points=6),
        _row(5, minutes=70, started=True, points=3),
        _row(8, minutes=21, started=False, points=0, yellow=1),
        _row(13, minutes=90, started=True, points=5),
    ]
    result = reconcile_owned_match_events(_locked(), rows)
    assert result["status"] == "PASS"
    assert result["completed_or_live_owned_expected"] == 4
    assert result["completed_or_live_owned_reconciled"] == 4
    assert result["coverage_complete"] is True


def test_h_identity_join_uses_element_id_and_never_name_guessing():
    rows = [
        {**_row(8, minutes=21, started=False, points=0), "name": "Wrong Name"},
        {"name": "P13", "fixture_status": "FT", "minutes": 90, "total_points": 10},
    ]
    result = reconcile_owned_match_events(_locked(), rows)
    assert [row["element_id"] for row in result["players"]] == [8]
    assert result["players"][0]["identity_join"] == "CANONICAL_ELEMENT_ID"
    assert result["identity_join"] == "CANONICAL_ELEMENT_ID_ONLY"

def test_two_xi_dnp_cannot_consume_same_bench_player():
    result = reconcile_owned_match_events(
        _locked(),
        [
            _row(2, minutes=0),
            _row(8, minutes=0),
            _row(12, minutes=0),
            _row(13, minutes=90, started=True, points=6),
            _row(14, minutes=0),
            _row(15, minutes=0),
        ],
    )
    subs = result["final_substitution_map"]
    assert subs["2"] == 13
    assert subs["8"] == "no_legal_sub"
    assert result["autosub_resolution"]["consumed_bench"] == [13]


def test_two_dnp_receive_two_distinct_legal_bench_replacements():
    result = reconcile_owned_match_events(
        _locked(),
        [
            _row(2, minutes=0),
            _row(8, minutes=0),
            _row(12, minutes=0),
            _row(13, minutes=90, started=True, points=6),
            _row(14, minutes=70, started=True, points=4),
            _row(15, minutes=0),
        ],
    )
    subs = result["final_substitution_map"]
    assert subs == {"2": 13, "8": 14}
    assert result["autosub_resolution"]["consumed_bench"] == [13, 14]


def test_formation_constraint_changes_second_substitution_result():
    result = reconcile_owned_match_events(
        _locked(),
        [
            _row(2, minutes=0),
            _row(8, minutes=0),
            _row(12, minutes=0),
            _row(13, minutes=0),
            _row(14, minutes=80, started=True, points=5),
            _row(15, minutes=80, started=True, points=5),
        ],
    )
    subs = result["final_substitution_map"]
    assert subs["8"] == 14
    assert subs["2"] == "no_legal_sub"
    assert result["autosub_resolution"]["consumed_bench"] == [14]


def test_first_unavailable_bench_is_skipped_and_next_eligible_is_used():
    result = reconcile_owned_match_events(
        _locked(),
        [
            _row(8, minutes=0),
            _row(12, minutes=0),
            _row(13, minutes=0),
            _row(14, minutes=75, started=True, points=3),
            _row(15, minutes=0),
        ],
    )
    assert result["final_substitution_map"]["8"] == 14
    player = next(row for row in result["players"] if row["element_id"] == 8)
    assert player["autosub"] == {"status": "ACTIVATES", "element_id": 14}


def test_simultaneous_gk_and_outfield_dnp_use_distinct_legal_replacements():
    result = reconcile_owned_match_events(
        _locked(),
        [
            _row(1, minutes=0),
            _row(8, minutes=0),
            _row(12, minutes=90, started=True, points=4),
            _row(13, minutes=90, started=True, points=6),
            _row(14, minutes=0),
            _row(15, minutes=0),
        ],
    )
    assert result["final_substitution_map"] == {"1": 12, "8": 13}
    assert result["autosub_resolution"]["consumed_bench"] == [12, 13]


def test_cameo_starter_blocks_only_itself_while_other_dnp_resolves_normally():
    result = reconcile_owned_match_events(
        _locked(),
        [
            _row(8, minutes=21, started=False, points=0, yellow=1),
            _row(11, minutes=0),
            _row(12, minutes=0),
            _row(13, minutes=90, started=True, points=5),
            _row(14, minutes=0),
            _row(15, minutes=0),
        ],
    )
    cameo = next(row for row in result["players"] if row["element_id"] == 8)
    dnp = next(row for row in result["players"] if row["element_id"] == 11)
    assert cameo["personal_state"] == "CAMEO_BLOCKED_AUTOSUB"
    assert "8" not in result["final_substitution_map"]
    assert result["final_substitution_map"]["11"] == 13
    assert dnp["personal_state"] == "DNP_WITH_AUTOSUB_POSSIBLE"


def test_pending_earlier_bench_does_not_finalize_later_replacement():
    result = reconcile_owned_match_events(
        _locked(),
        [
            _row(8, minutes=0),
            _row(12, minutes=0),
            # element 13 has not finished/appeared yet and is intentionally absent.
            _row(14, minutes=90, started=True, points=5),
            _row(15, minutes=0),
        ],
    )
    assert result["final_substitution_map"]["8"] == "pending"
    assert result["autosub_resolution"]["status"] == "PENDING"
    assert 13 in result["autosub_resolution"]["pending_bench"]
    player = next(row for row in result["players"] if row["element_id"] == 8)
    assert player["personal_state"] == "DNP_AUTOSUB_PENDING"
    assert player["autosub"] == {"status": "PENDING"}

