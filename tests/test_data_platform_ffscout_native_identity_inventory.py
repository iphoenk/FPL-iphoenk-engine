from __future__ import annotations

import pytest

from src.runtime_v6.ffscout_public import (
    FFScoutPublicError,
    augment_ffscout_public_dataset,
    build_ffscout_public_dataset,
)


def _img(code: int, name: str) -> str:
    return f'<img src="https://resources.premierleague.com/premierleague/photos/players/110x140/{code}.png" alt="Avatar of {name}">'


def _payload() -> dict:
    return {
        "checked_at": "2026-09-13T00:00:00Z",
        "health": "GREEN",
        "effective_state": "LIVE_CHANGED",
        "current_run_action": "FETCHED",
        "data": {
            "team_news": {"body": _img(84146, "Example Player"), "sha256": "a"},
            "home": {"body": _img(84146, "Example Player"), "sha256": "b"},
        },
    }


def _identity() -> dict:
    return {
        "mappings": {
            "10": {
                "official_fpl_element_id": 10,
                "links": {
                    "ffscout": {
                        "source_native_id": 84146,
                        "status": "EXACT",
                        "joinable": True,
                    }
                },
            }
        }
    }


def test_build_consolidates_same_native_id_across_public_request_surfaces():
    dataset = build_ffscout_public_dataset(_payload(), _identity())
    rows = dataset["record_groups"]["players"]
    assert len(rows) == 1
    row = rows[0]
    assert row["source_native_id"] == 84146
    assert row["official_element_id"] == 10
    assert row["identity_status"] == "EXACT"
    assert row["request_ids"] == ["home", "team_news"]
    assert row["observation_count"] == 2
    assert len(row["observations"]) == 2
    assert row["observation_type"] == "PREDICTED_LINEUP_PUBLIC_REFERENCE"
    assert dataset["governance"]["player_identity_rows_are_unique_by_source_native_id"] is True
    assert dataset["governance"]["observation_evidence_is_retained"] is True


def test_augment_collapses_legacy_duplicate_rows_and_preserves_evidence():
    existing = {
        "ffscout": {
            "record_groups": {
                "players": [
                    {"source_native_id": 84146, "request_id": "home", "image_url": "home.png", "official_element_id": None, "identity_status": "UNMAPPED"},
                    {"source_native_id": 84146, "request_id": "team_news", "image_url": "news.png", "official_element_id": 10, "identity_status": "EXACT", "join_ready": True, "identity_method": "legacy"},
                ]
            },
            "governance": {},
        }
    }
    out = augment_ffscout_public_dataset({"ffscout": _payload()}, _identity(), existing)
    rows = out["ffscout"]["record_groups"]["players"]
    assert len(rows) == 1
    row = rows[0]
    assert row["source_native_id"] == 84146
    assert row["official_element_id"] == 10
    assert row["identity_status"] == "EXACT"
    assert row["request_ids"] == ["home", "team_news"]
    assert {item["image_url"] for item in row["observations"]} >= {"home.png", "news.png"}
    assert out["ffscout"]["governance"]["multiple_observations_for_same_native_id_are_consolidated"] is True


def test_augment_fails_closed_if_same_native_id_targets_multiple_official_elements():
    existing = {
        "ffscout": {
            "record_groups": {
                "players": [
                    {"source_native_id": 84146, "request_id": "home", "official_element_id": 10, "identity_status": "EXACT"},
                    {"source_native_id": 84146, "request_id": "team_news", "official_element_id": 11, "identity_status": "EXACT"},
                ]
            },
            "governance": {},
        }
    }
    with pytest.raises(FFScoutPublicError, match="multiple Official FPL elements"):
        augment_ffscout_public_dataset({"ffscout": _payload()}, _identity(), existing)
