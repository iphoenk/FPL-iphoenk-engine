import json
from pathlib import Path


CONFIG = Path(__file__).resolve().parents[1] / "config" / "v6" / "verified_crosswalks.json"

# Wave 1 acceptance is pinned to the current Official FPL canonical code + element id.
EXPECTED = {
    12847: (627221, 599),  # Sidiki Cherif
    13078: (592984, 639),  # Chema Andres
    8190: (437497, 637),   # Melvin Bard
}


def test_wave1_understat_actionable_crosswalks_are_deterministic():
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    understat = payload["sources"]["understat"]
    rows = {int(row["source_native_id"]): row for row in understat["players"]}

    for native_id, (official_code, element_id) in EXPECTED.items():
        assert native_id in rows
        row = rows[native_id]
        assert int(row["official_fpl_code"]) == official_code
        assert int(row["official_fpl_element_id"]) == element_id
        assert row["verification_method"] == "WAVE1_OFFICIAL_FPL_CODE_TO_OBSERVED_UNDERSTAT_NATIVE_ID"
        assert row["review_status"] == "DETERMINISTIC_BRIDGE_REVIEWED"
        assert row["bridge_path"] == [
            "official_fpl.bootstrap.elements.code",
            "understat.observed_native_player_id",
            "official_fpl.bootstrap.elements.id",
        ]
        assert row["evidence"]


def test_wave1_understat_crosswalk_has_no_duplicate_native_or_official_code():
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    rows = payload["sources"]["understat"]["players"]
    native_ids = [str(row["source_native_id"]) for row in rows]
    official_codes = [int(row["official_fpl_code"]) for row in rows]
    assert len(native_ids) == len(set(native_ids))
    assert len(official_codes) == len(set(official_codes))
