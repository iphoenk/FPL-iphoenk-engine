from datetime import datetime, timezone

from src.v5.evaluation.decision_validation import capture


def _context():
    return {
        "planning_gw": 3,
        "deadline_time": "2026-09-04T17:30:00Z",
        "phase": "PRE_DEADLINE",
    }


def _team(authority: str):
    return {
        "authority": authority,
        "squad": [
            {"element": i, "position": "GK" if i <= 2 else "DEF" if i <= 7 else "MID" if i <= 12 else "FWD"}
            for i in range(1, 16)
        ],
    }


def _decision(captain: int = 8):
    return {
        "lineup": {
            "starters": [
                {"element": i, "position": "GK" if i == 1 else "DEF" if i <= 5 else "MID" if i <= 9 else "FWD"}
                for i in range(1, 12)
            ],
            "captain": {"element": captain},
            "vice_captain": {"element": 10},
        }
    }


def test_same_material_predeadline_snapshot_is_not_revised():
    first = capture(
        _context(),
        _decision(),
        _team("official_public"),
        {},
        now=datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc),
    )
    second = capture(
        _context(),
        _decision(),
        _team("official_public"),
        {},
        previous=first,
        now=datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc),
    )
    assert second["last_capture"]["status"] == "ALREADY_FROZEN"
    assert second["records"]["3"]["revision"] == 1
    assert second["revision_history"].get("3", []) == []


def test_material_predeadline_authority_correction_is_append_only_revision():
    first = capture(
        _context(),
        _decision(captain=8),
        _team("user_lock"),
        {},
        now=datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc),
    )
    corrected = capture(
        _context(),
        _decision(captain=9),
        _team("official_public"),
        {},
        previous=first,
        now=datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc),
    )
    assert corrected["last_capture"]["status"] == "PREDEADLINE_REVISION_CAPTURED"
    assert corrected["records"]["3"]["revision"] == 2
    assert corrected["records"]["3"]["decision_authority"] == "official_public"
    assert corrected["records"]["3"]["lineup"]["captain"] == 9
    assert corrected["records"]["3"]["supersedes_captured_at"] == first["records"]["3"]["captured_at"]
    assert len(corrected["revision_history"]["3"]) == 1
    assert corrected["revision_history"]["3"][0] == first["records"]["3"]
    assert corrected["revision_history"]["3"][0]["decision_authority"] == "user_lock"


def test_material_predeadline_decision_change_creates_another_revision_without_losing_history():
    first = capture(
        _context(),
        _decision(captain=8),
        _team("official_public"),
        {},
        now=datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc),
    )
    second = capture(
        _context(),
        _decision(captain=9),
        _team("official_public"),
        {},
        previous=first,
        now=datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc),
    )
    third = capture(
        _context(),
        _decision(captain=10),
        _team("official_public"),
        {},
        previous=second,
        now=datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc),
    )
    assert third["records"]["3"]["revision"] == 3
    assert third["records"]["3"]["lineup"]["captain"] == 10
    assert [row["revision"] for row in third["revision_history"]["3"]] == [1, 2]


def test_postdeadline_capture_never_supersedes_existing_revision():
    first = capture(
        _context(),
        _decision(captain=8),
        _team("official_public"),
        {},
        now=datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc),
    )
    late = capture(
        _context(),
        _decision(captain=9),
        _team("official_authenticated"),
        {},
        previous=first,
        now=datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc),
    )
    assert late["last_capture"]["status"] == "NO_PREDEADLINE_CAPTURE"
    assert late["records"]["3"] == first["records"]["3"]
    assert late["revision_history"].get("3", []) == []
