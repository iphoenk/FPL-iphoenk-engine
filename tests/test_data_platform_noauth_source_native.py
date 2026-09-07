from __future__ import annotations

from src.runtime_v6.noauth_source_native import build_noauth_source_native_datasets


def _source(data: dict) -> dict:
    return {
        "checked_at": "2026-09-07T01:00:00+00:00",
        "health": "GREEN",
        "effective_state": "LIVE_CHANGED",
        "current_run_action": "FETCHED",
        "data": data,
    }


def _request(payload, digest: str = "abc") -> dict:
    return {"json": payload, "sha256": digest}


def test_reep_normalizes_public_release_without_keyed_api_authority() -> None:
    results = {
        "reep_register": _source(
            {
                "latest_manifest": _request({"release": "2026-09-03", "assets": [{"name": "register.csv"}]}),
                "downloads_contract": {"body": "Download the register CC0 1.0 Latest release", "sha256": "def"},
            }
        )
    }
    dataset = build_noauth_source_native_datasets(results, {})["reep_register"]
    assert dataset["normalization_status"] == "NORMALIZED"
    assert dataset["record_groups"]["release"][0]["keyed_api_used"] is False
    assert dataset["record_groups"]["release"][0]["bulk_asset_downloaded"] is False
    assert dataset["authority_ceiling"] == "IDENTITY_CORROBORATION_ONLY"
    assert dataset["governance"]["may_override_official_fpl"] is False


def test_wikidata_preserves_qid_without_fuzzy_official_join() -> None:
    results = {
        "wikidata": _source(
            {
                "premier_league_clubs": _request(
                    {
                        "results": {
                            "bindings": [
                                {
                                    "club": {"value": "http://www.wikidata.org/entity/Q9617"},
                                    "clubLabel": {"value": "Arsenal F.C."},
                                    "website": {"value": "https://www.arsenal.com/"},
                                }
                            ]
                        }
                    }
                )
            }
        )
    }
    row = build_noauth_source_native_datasets(results, {})["wikidata"]["record_groups"]["teams"][0]
    assert row["source_native_id"] == "Q9617"
    assert row["official_team_id"] is None
    assert row["identity_status"] == "UNMAPPED"


def test_open_meteo_is_typed_upstream_signal_without_fpl_computation() -> None:
    results = {
        "open_meteo": _source(
            {
                "premier_league_venues": _request(
                    [
                        {
                            "latitude": 50.73,
                            "longitude": -1.84,
                            "timezone": "GMT",
                            "hourly_units": {"temperature_2m": "°C"},
                            "hourly": {"time": ["2026-09-07T01:00"], "temperature_2m": [14.2]},
                        }
                    ]
                )
            }
        )
    }
    dataset = build_noauth_source_native_datasets(results, {})["open_meteo"]
    row = dataset["record_groups"]["venue_forecasts"][0]
    assert dataset["semantic_class"] == "UPSTREAM_MODEL_SIGNAL"
    assert dataset["model_author"] == "OPEN_METEO"
    assert dataset["v6_computation"] == "NONE"
    assert dataset["governance"]["weather_fpl_interpretation"] == "DOWNSTREAM_ONLY"
    assert row["club"] == "AFC Bournemouth"
    assert row["official_fixture_id"] is None


def test_thesportsdb_keeps_source_native_fixture_ids_only() -> None:
    results = {
        "thesportsdb_v1": _source(
            {
                "league": _request({"leagues": [{"idLeague": "4328", "strLeague": "English Premier League"}]}),
                "next_event": _request(
                    {
                        "events": [
                            {
                                "idEvent": "12345",
                                "idLeague": "4328",
                                "strEvent": "Arsenal vs Chelsea",
                                "idHomeTeam": "133604",
                                "strHomeTeam": "Arsenal",
                                "idAwayTeam": "133610",
                                "strAwayTeam": "Chelsea",
                                "strTimestamp": "2026-09-12T14:00:00",
                            }
                        ]
                    }
                ),
                "past_event": _request({"events": []}),
            }
        )
    }
    dataset = build_noauth_source_native_datasets(results, {})["thesportsdb_v1"]
    event = dataset["record_groups"]["events"][0]
    assert event["source_native_id"] == "12345"
    assert event["official_fixture_id"] is None
    assert event["identity_status"] == "UNMAPPED"
    assert dataset["authority_ceiling"] == "SECONDARY"


def test_builder_only_emits_present_noauth_sources() -> None:
    results = {"wikidata": _source({"premier_league_clubs": _request({"results": {"bindings": []}})})}
    assert set(build_noauth_source_native_datasets(results, {})) == {"wikidata"}
