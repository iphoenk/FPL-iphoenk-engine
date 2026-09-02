from __future__ import annotations

import json

from src.intelligence import understat_runtime_reconcile as reconcile


def test_latest_match_covered_ignores_future_schedule() -> None:
    raw = {
        "embedded": {
            "datesData": [
                {"datetime": "2026-08-31 19:00:00", "isResult": True, "goals": {"h": 2, "a": 1}},
                {"datetime": "2027-05-30 15:00:00", "isResult": False, "goals": {"h": None, "a": None}},
            ]
        }
    }
    assert reconcile.latest_completed_match_covered(raw) == "2026-08-31 19:00:00"


def test_latest_fixture_represented_is_governed_completed_authority() -> None:
    raw = {
        "latest_fixture_represented": {"id": "1", "datetime": "2026-09-01 20:00:00"},
        "embedded": {"datesData": []},
    }
    assert reconcile.latest_completed_match_covered(raw) == "2026-09-01 20:00:00"


def test_unlinked_source_rows_distinguish_current_identity_from_historical_residue() -> None:
    raw = {
        "embedded": {
            "playersData": [
                {"id": "10", "player_name": "Alpha Player", "team_title": "Old Club"},
                {"id": "20", "player_name": "Bravo", "team_title": "Current Club"},
                {"id": "30", "player_name": "Departed Person", "team_title": "Old Club"},
            ]
        }
    }
    tactical = {
        "player_evidence": {
            "1": {
                "element": 1,
                "canonical_identity": {
                    "element": 1,
                    "name": "Alpha Player",
                    "web_name": "Alpha",
                    "name_variants": ["Alpha Player", "Alpha"],
                },
                "mapping": {"state": "UNRESOLVED"},
            },
            "2": {
                "element": 2,
                "canonical_identity": {"element": 2, "name": "Bravo", "web_name": "Bravo"},
                "understat_player_id": "20",
                "mapping": {"state": "RESOLVED"},
            },
        }
    }
    rows = reconcile.classify_unlinked_source_players(raw, tactical)
    by_id = {row["understat_player_id"]: row for row in rows}
    assert by_id["10"]["classification"] == "CURRENT_OFFICIAL_IDENTITY_UNLINKED"
    assert by_id["10"]["review_required"] is True
    assert by_id["30"]["classification"] == "NOT_IN_CURRENT_OFFICIAL_UNIVERSE"
    assert by_id["30"]["review_required"] is False


def test_reconcile_marks_green_only_for_complete_current_universe(monkeypatch, tmp_path) -> None:
    raw_path = tmp_path / "understat.json"
    tactical_path = tmp_path / "tactical.json"
    health_path = tmp_path / "health.json"
    latest_path = tmp_path / "latest.json"
    raw_path.write_text(
        json.dumps(
            {
                "latest_fixture_represented": {"datetime": "2026-08-31 19:00:00"},
                "embedded": {"playersData": [{"id": "20", "player_name": "Bravo", "team_title": "Current Club"}]},
            }
        ),
        encoding="utf-8",
    )
    latest_path.write_text(json.dumps({"understat_tactical_summary": {}}), encoding="utf-8")
    monkeypatch.setattr(reconcile, "RAW_CACHE", raw_path)
    monkeypatch.setattr(reconcile, "TACTICAL_OUT", tactical_path)
    monkeypatch.setattr(reconcile, "HEALTH_OUT", health_path)
    monkeypatch.setattr(reconcile, "LATEST_OUT", latest_path)

    out = {
        "tactical": {
            "source": {},
            "player_evidence": {
                "2": {
                    "element": 2,
                    "canonical_identity": {"element": 2, "name": "Bravo", "web_name": "Bravo"},
                    "understat_player_id": "20",
                    "mapping": {"state": "RESOLVED"},
                }
            },
        },
        "health": {
            "source": {},
            "coverage": {"official_universe_count": 1, "canonical_identity_mapping_complete": True},
            "canonical_merge": {"player_profiles_enriched": 1},
            "governance": {},
        },
    }
    reconciled = reconcile.reconcile(out)
    coverage = reconciled["health"]["coverage"]
    assert reconciled["health"]["production_parity_status"] == "GREEN"
    assert coverage["full_current_universe_parity_ready"] is True
    assert coverage["source_player_mapping_review_required_count"] == 0
    assert reconciled["health"]["source"]["latest_match_covered"] == "2026-08-31 19:00:00"


def test_reconcile_keeps_parity_in_review_when_current_identity_is_unlinked(monkeypatch, tmp_path) -> None:
    raw_path = tmp_path / "understat.json"
    tactical_path = tmp_path / "tactical.json"
    health_path = tmp_path / "health.json"
    latest_path = tmp_path / "latest.json"
    raw_path.write_text(
        json.dumps({"embedded": {"playersData": [{"id": "10", "player_name": "Alpha Player", "team_title": "Old Club"}]}}),
        encoding="utf-8",
    )
    latest_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(reconcile, "RAW_CACHE", raw_path)
    monkeypatch.setattr(reconcile, "TACTICAL_OUT", tactical_path)
    monkeypatch.setattr(reconcile, "HEALTH_OUT", health_path)
    monkeypatch.setattr(reconcile, "LATEST_OUT", latest_path)

    out = {
        "tactical": {
            "source": {},
            "player_evidence": {
                "1": {
                    "element": 1,
                    "canonical_identity": {"element": 1, "name": "Alpha Player", "web_name": "Alpha"},
                    "mapping": {"state": "UNRESOLVED"},
                }
            },
        },
        "health": {
            "source": {},
            "coverage": {"official_universe_count": 1, "canonical_identity_mapping_complete": True},
            "canonical_merge": {"player_profiles_enriched": 1},
            "governance": {},
        },
    }
    reconciled = reconcile.reconcile(out)
    coverage = reconciled["health"]["coverage"]
    assert reconciled["health"]["production_parity_status"] == "REVIEW_REQUIRED"
    assert coverage["full_current_universe_parity_ready"] is False
    assert coverage["source_player_mapping_review_required_count"] == 1
