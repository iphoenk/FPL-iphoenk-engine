from __future__ import annotations

from src.runtime_v6.player_observation import augment_source_native_datasets


def _identity() -> dict:
    return {
        "mappings": {
            "1": {
                "official_fpl_element_id": 1,
                "links": {
                    "fotmob": {"source_native_id": 601, "status": "VERIFIED_MANUAL", "joinable": True},
                    "statmuse": {"source_native_id": 701, "status": "VERIFIED_MANUAL", "joinable": True},
                },
            }
        }
    }


def test_fotmob_player_leaders_are_normalized_by_native_id_only():
    results = {
        "fotmob": {
            "checked_at": "2026-09-13T10:00:00+00:00",
            "health": "GREEN",
            "effective_state": "LIVE_CHANGED",
            "current_run_action": "FETCHED",
            "data": {
                "league": {
                    "sha256": "a" * 64,
                    "json": {
                        "stats": {
                            "players": [
                                {
                                    "title": "Goals",
                                    "topThree": [
                                        {"id": 601, "name": "Wrong Name Does Not Matter", "teamId": 10, "value": 3},
                                        {"id": 602, "name": "Unmapped", "teamId": 11, "value": 2},
                                    ],
                                }
                            ]
                        }
                    },
                }
            },
        }
    }

    datasets = augment_source_native_datasets(results, _identity(), {})
    players = datasets["fotmob"]["record_groups"]["players"]
    mapped = next(row for row in players if row["source_native_id"] == 601)
    unmapped = next(row for row in players if row["source_native_id"] == 602)

    assert mapped["official_element_id"] == 1
    assert mapped["join_ready"] is True
    assert unmapped["official_element_id"] is None
    assert unmapped["join_ready"] is False
    assert datasets["fotmob"]["governance"]["silent_fuzzy_identity_join"] is False


def test_statmuse_table_uses_numeric_player_href_not_name_for_identity():
    html = """
    <table>
      <tr><th>NAME</th><th>xG</th><th>xA</th><th>SEASON</th><th>CLUB</th><th>MIN</th><th>START</th><th>G</th><th>A</th><th>SH</th><th>SOT</th><th>TCH</th><th>TCH-BOX</th></tr>
      <tr><td><a href="/fc/player/not-the-canonical-name-701">Completely Different Display Name</a></td><td>2.21</td><td>0.59</td><td>2026-27</td><td>Club</td><td>270</td><td>3</td><td>3</td><td>1</td><td>15</td><td>4</td><td>263</td><td>11</td></tr>
      <tr><td><a href="/fc/player/unmapped-702">Unmapped Player</a></td><td>1.00</td><td>0.10</td><td>2026-27</td><td>Club</td><td>180</td><td>2</td><td>1</td><td>0</td><td>6</td><td>2</td><td>100</td><td>5</td></tr>
    </table>
    """
    results = {
        "statmuse": {
            "checked_at": "2026-09-13T10:00:00+00:00",
            "health": "GREEN",
            "effective_state": "LIVE_CHANGED",
            "current_run_action": "FETCHED",
            "data": {"player_xg": {"sha256": "b" * 64, "body": html}},
        }
    }

    datasets = augment_source_native_datasets(results, _identity(), {})
    players = datasets["statmuse"]["record_groups"]["players"]
    mapped = next(row for row in players if row["source_native_id"] == 701)

    assert mapped["official_element_id"] == 1
    assert mapped["join_ready"] is True
    assert mapped["xg"] == 2.21
    assert mapped["xa"] == 0.59
    assert mapped["minutes"] == 270
    assert datasets["statmuse"]["governance"]["identity_join_requires_verified_provider_native_id"] is True
