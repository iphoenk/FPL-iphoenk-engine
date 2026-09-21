from __future__ import annotations

from src.runtime_v6.domains.report_plane.official_match_history import (
    build_official_match_history,
)


def _result(endpoint, payload, status="LIVE", checked="2026-09-21T14:20:00+00:00"):
    return {
        "status": status,
        "endpoint_class": endpoint,
        "checked_at": checked,
        "http_status": 200 if status == "LIVE" else 503,
        "payload_digest": f"{endpoint}-{checked}",
        "payload": payload if status == "LIVE" else None,
        "attempts": 1,
        "duration_ms": 1,
        "error": None,
    }


def _bootstrap():
    return {
        "events": [
            {"id": 1, "finished": True},
            {"id": 2, "finished": True},
            {"id": 3, "finished": False},
        ],
        "element_types": [
            {"id": 1, "singular_name_short": "GKP"},
            {"id": 2, "singular_name_short": "DEF"},
            {"id": 3, "singular_name_short": "MID"},
            {"id": 4, "singular_name_short": "FWD"},
        ],
        "elements": [
            {"id": 10, "team": 1, "element_type": 3},
            {"id": 20, "team": 2, "element_type": 4},
        ],
    }


def _stats(points):
    return {
        "minutes": 90,
        "starts": 1,
        "total_points": points,
        "goals_scored": 1,
        "assists": 0,
        "expected_goals": "0.45",
        "expected_assists": "0.12",
        "expected_goal_involvements": "0.57",
        "expected_goals_conceded": "0.80",
        "clean_sheets": 0,
        "goals_conceded": 1,
        "saves": 0,
        "penalties_saved": 0,
        "penalties_missed": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "bonus": 2,
        "bps": 30,
        "defensive_contribution": 4,
        "clearances_blocks_interceptions": 1,
        "recoveries": 3,
        "tackles": 1,
        "creativity": "14.0",
        "influence": "25.0",
        "threat": "40.0",
    }


class FakeClient:
    def __init__(self, *, dgw=False, missing_gw=None):
        self.dgw = dgw
        self.missing_gw = missing_gw

    def fixtures(self):
        fixtures = [
            {
                "id": 101,
                "event": 1,
                "team_h": 1,
                "team_a": 2,
                "team_h_score": 2,
                "team_a_score": 1,
                "kickoff_time": "2026-08-22T14:00:00Z",
                "finished": True,
            },
            {
                "id": 201,
                "event": 2,
                "team_h": 2,
                "team_a": 1,
                "team_h_score": 0,
                "team_a_score": 1,
                "kickoff_time": "2026-08-29T14:00:00Z",
                "finished": True,
            },
        ]
        if self.dgw:
            fixtures.append(
                {
                    "id": 202,
                    "event": 2,
                    "team_h": 1,
                    "team_a": 3,
                    "team_h_score": 1,
                    "team_a_score": 1,
                    "kickoff_time": "2026-09-01T18:00:00Z",
                    "finished": True,
                }
            )
        return _result("fixtures", fixtures)

    def event_live(self, gw):
        if gw == self.missing_gw:
            return _result("event_live", None, status="FAILED")
        return _result(
            "event_live",
            {
                "elements": [
                    {"id": 10, "stats": _stats(8 + gw)},
                    {"id": 20, "stats": _stats(6 + gw)},
                ]
            },
            checked=f"2026-09-21T14:2{gw}:00+00:00",
        )


def test_completed_gws_are_normalized_with_exact_official_identity():
    artifact = build_official_match_history(
        FakeClient(),
        bootstrap_result=_result("bootstrap_static", _bootstrap()),
        generated_at="2026-09-21T14:30:00+00:00",
    )
    assert artifact["status"] == "COMPLETE"
    assert artifact["completed_gws_expected"] == [1, 2]
    assert artifact["completed_gws_available"] == [1, 2]
    assert artifact["missing_gws"] == []
    assert artifact["ambiguous_fixture_rows"] == 0
    rows = artifact["record_groups"]["player_matches"]
    assert len(rows) == 4
    assert {row["gw"] for row in rows} == {1, 2}
    assert all(row["identity_status"] == "EXACT" for row in rows)
    assert all(row["fixture_identity_status"] == "EXACT" for row in rows)
    assert all(row["opponent_identity_status"] == "EXACT" for row in rows)
    assert all(row["starter"] is True for row in rows)
    assert rows[0]["xg"] == 0.45


def test_missing_completed_gw_fails_closed():
    artifact = build_official_match_history(
        FakeClient(missing_gw=2),
        bootstrap_result=_result("bootstrap_static", _bootstrap()),
        generated_at="2026-09-21T14:30:00+00:00",
    )
    assert artifact["status"] == "PARTIAL"
    assert artifact["missing_gws"] == [2]
    assert any(
        "OFFICIAL_EVENT_LIVE_MISSING_GWS=2" == blocker
        for blocker in artifact["blockers"]
    )


def test_multi_fixture_ambiguity_is_rejected_not_split_or_guessed():
    artifact = build_official_match_history(
        FakeClient(dgw=True),
        bootstrap_result=_result("bootstrap_static", _bootstrap()),
        generated_at="2026-09-21T14:30:00+00:00",
    )
    assert artifact["status"] == "PARTIAL"
    assert artifact["ambiguous_fixture_rows"] > 0
    assert artifact["governance"]["fixture_guessing"] is False
    assert artifact["governance"]["ambiguous_multi_fixture_rows_rejected"] is True
