from __future__ import annotations

from datetime import datetime, timezone

from src.runtime_v6.health import build_source_health
from src.runtime_v6.identity_scope import apply_entity_scope_identity_semantics


def _unresolved_player_row(canonical: int = 3) -> dict:
    return {
        "strategy": "UNRESOLVED_NO_VERIFIED_DETERMINISTIC_BRIDGE",
        "deterministic_bridge": False,
        "identity_health": "RED",
        "mapped_status": "UNMAPPED",
        "mapped_player_count": 0,
        "canonical_player_count": canonical,
        "coverage_ratio": 0.0,
        "unmapped_player_count": canonical,
        "join_allowed": False,
    }


def _identity_map() -> dict:
    statsbomb = _unresolved_player_row()
    rotowire = _unresolved_player_row()
    return {
        "canonical_authority": "official_fpl",
        "canonical_player_count": 3,
        "coverage": {
            "statsbomb": dict(statsbomb),
            "rotowire": dict(rotowire),
        },
        "entity_bridges": {
            "player": {
                "canonical_authority": "official_fpl",
                "canonical_key": "official_fpl_element_id",
                "identity_health": "RED",
                "canonical_player_count": 3,
                "coverage": {
                    "statsbomb": dict(statsbomb),
                    "rotowire": dict(rotowire),
                },
            },
            "team": {
                "canonical_team_count": 2,
                "coverage": {},
            },
            "fixture": {
                "canonical_fixture_count": 4,
                "coverage": {},
            },
        },
    }


def test_player_not_applicable_semantics_propagate_to_player_bridge() -> None:
    identity = apply_entity_scope_identity_semantics(
        _identity_map(),
        {
            "official_fpl": ["PLAYER", "TEAM", "FIXTURE"],
            "statsbomb": ["COMPETITION", "EVENT", "FEED"],
            "rotowire": ["PLAYER"],
        },
    )

    source_row = identity["coverage"]["statsbomb"]
    bridge_row = identity["entity_bridges"]["player"]["coverage"]["statsbomb"]

    assert source_row["identity_health"] == "NOT_APPLICABLE"
    assert source_row["join_allowed"] is False
    assert source_row["applicable"] is False
    assert bridge_row["identity_health"] == "NOT_APPLICABLE"
    assert bridge_row["join_allowed"] is False
    assert bridge_row["applicable"] is False
    assert bridge_row["strategy"] == "NOT_APPLICABLE_FOR_ENTITY_SCOPE"

    unresolved = identity["entity_bridges"]["player"]["coverage"]["rotowire"]
    assert unresolved["identity_health"] == "RED"
    assert unresolved["join_allowed"] is False
    assert unresolved["applicable"] is True


def test_source_health_consumes_canonical_source_entity_identity() -> None:
    now = datetime.now(timezone.utc).isoformat()
    identity = {
        "coverage": {
            "provider": {
                "identity_health": "GREEN",
                "join_allowed": True,
                "applicable": True,
            }
        },
        "entity_bridges": {
            "team": {"coverage": {}},
            "fixture": {"coverage": {}},
        },
        "source_entity_identity": {
            "provider": {
                "entity_scopes": ["PLAYER"],
                "player": {
                    "identity_health": "AMBER",
                    "join_allowed": True,
                    "applicable": True,
                },
                "team": {
                    "identity_health": "NOT_APPLICABLE",
                    "join_allowed": False,
                    "applicable": False,
                },
                "fixture": {
                    "identity_health": "NOT_APPLICABLE",
                    "join_allowed": False,
                    "applicable": False,
                },
                "identity_health": "AMBER",
            }
        },
    }
    config = {
        "sources": [
            {
                "id": "provider",
                "name": "Provider",
                "category": "advanced_performance",
                "critical": False,
                "entity_scopes": ["PLAYER"],
                "check_freshness_minutes": 90,
            }
        ]
    }
    results = {
        "provider": {
            "source_id": "provider",
            "checked_at": now,
            "health": "GREEN",
            "availability": "AVAILABLE",
            "coverage": {"expected_requests": 1, "usable_requests": 1},
            "polling": {"skipped": False},
            "attempts": [],
            "data": {},
        }
    }

    health = build_source_health(config, results, identity)
    row = health["sources"][0]

    assert row["dimensions"]["identity_health"] == "AMBER"
    assert row["identity_by_scope"] == {"PLAYER": "AMBER"}
    assert health["dimension_counts"]["identity_health"] == {
        "GREEN": 0,
        "AMBER": 1,
        "RED": 0,
        "NOT_APPLICABLE": 0,
    }
    assert sum(health["dimension_counts"]["identity_health"].values()) == health["source_count"]
    assert row["dimensions"]["transport_health"] == "GREEN"
    assert row["health"] == "GREEN"
