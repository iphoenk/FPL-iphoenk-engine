from __future__ import annotations

from src.runtime_v6.ffscout_public import (
    METHOD,
    build_ffscout_public_dataset,
    enrich_ffscout_public_identity,
)


def _identity_map() -> dict:
    return {
        "canonical_player_count": 3,
        "coverage": {},
        "mappings": {
            "1": {
                "official_fpl_element_id": 1,
                "official_code": 154561,
                "links": {},
                "unresolved": {"ffscout": "UNMAPPED"},
            },
            "2": {
                "official_fpl_element_id": 2,
                "official_code": 244851,
                "links": {},
                "unresolved": {"ffscout": "UNMAPPED"},
            },
            "3": {
                "official_fpl_element_id": 3,
                "official_code": 123456,
                "links": {},
                "unresolved": {"ffscout": "UNMAPPED"},
            },
        },
        "entity_bridges": {"player": {"coverage": {}}},
        "governance": {},
    }


def _payload() -> dict:
    return {
        "checked_at": "2026-09-13T11:00:00Z",
        "health": "GREEN",
        "effective_state": "LIVE",
        "current_run_action": "FETCHED",
        "data": {
            "team_news": {
                "body": """
                    <img alt="Avatar of Completely Wrong Display Name"
                         src="https://resources.premierleague.com/premierleague25/photos/players/110x140/154561.png" />
                    <img alt="Avatar of Palmer"
                         src="https://resources.premierleague.com/premierleague25/photos/players/110x140/244851.png" />
                    <img alt="Avatar of Unknown"
                         src="https://resources.premierleague.com/premierleague25/photos/players/110x140/999999.png" />
                """,
                "sha256": "team-news-sha",
            },
            "home": {
                "body": "<html><body>feed only</body></html>",
                "sha256": "home-sha",
            },
        },
    }


def test_ffscout_public_identity_uses_media_code_not_player_name():
    enriched = enrich_ffscout_public_identity(_identity_map(), {"ffscout": _payload()})

    link = enriched["mappings"]["1"]["links"]["ffscout"]
    assert link["source_native_id"] == 154561
    assert link["status"] == "EXACT"
    assert link["method"] == METHOD
    assert link["provenance"]["name_matching_used"] is False
    assert link["provenance"]["fuzzy_matching_used"] is False
    assert "ffscout" not in enriched["mappings"]["1"]["unresolved"]

    # Unknown embedded codes fail closed and are never attached to a canonical player.
    coverage = enriched["coverage"]["ffscout"]
    assert coverage["mapped_player_count"] == 2
    assert coverage["orphaned_observed_code_count"] == 1
    assert coverage["identity_health"] == "AMBER"
    assert coverage["name_matching_used"] is False


def test_ffscout_public_dataset_preserves_display_name_only_as_evidence():
    enriched = enrich_ffscout_public_identity(_identity_map(), {"ffscout": _payload()})
    dataset = build_ffscout_public_dataset(_payload(), enriched)

    rows = dataset["record_groups"]["players"]
    raya = next(row for row in rows if row["source_native_id"] == 154561)
    unknown = next(row for row in rows if row["source_native_id"] == 999999)

    assert raya["player_name"] == "Completely Wrong Display Name"
    assert raya["official_element_id"] == 1
    assert raya["join_ready"] is True
    assert raya["identity_method"] == METHOD

    assert unknown["official_element_id"] is None
    assert unknown["identity_status"] == "UNMAPPED"
    assert unknown["join_ready"] is False
    assert dataset["governance"]["member_paywalled_stats_not_acquired"] is True
    assert dataset["governance"]["prediction_authority"] == "NONE"
    assert dataset["governance"]["optimizer_authority"] == "NONE"


def test_duplicate_official_code_fails_closed():
    identity = _identity_map()
    identity["mappings"]["3"]["official_code"] = 154561
    enriched = enrich_ffscout_public_identity(identity, {"ffscout": _payload()})

    assert "ffscout" not in enriched["mappings"]["1"]["links"]
    assert "ffscout" not in enriched["mappings"]["3"]["links"]
    assert enriched["coverage"]["ffscout"]["duplicate_canonical_code_count"] == 1
