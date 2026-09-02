from __future__ import annotations

from src.sources import understat


def test_source_counts_are_observed_not_inferred() -> None:
    embedded = {
        "teamsData": {"1": {"id": "1"}, "2": {"id": "2"}},
        "playersData": [
            {"id": "10", "player_name": "Alpha"},
            {"id": "11", "player_name": "Bravo"},
            {"id": "12", "player_name": "Charlie"},
        ],
        "datesData": [{"id": "100"}, {"id": "101"}],
    }
    assert understat._source_counts(embedded) == {
        "team_count": 2,
        "player_count": 3,
        "fixture_count": 2,
    }


def test_unavailable_source_counts_are_zero_not_fabricated(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(understat, "CACHE", tmp_path / "understat.json")
    monkeypatch.setattr(understat, "POLICY_FILE", tmp_path / "policy.json")
    (tmp_path / "policy.json").write_text(
        '{"cache":{"retain_last_known_good":true},"network":{"transport_revision":"TEST"}}',
        encoding="utf-8",
    )
    payload = understat._failure("test failure", previous={})
    assert payload["source_availability"] == "UNAVAILABLE"
    assert payload["source_counts"] == {"team_count": 0, "player_count": 0, "fixture_count": 0}
