from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.runtime_v6.entity_scope import resolve_entity_scope_applicability
from src.runtime_v6.health import build_source_health
from src.runtime_v6.identity import build_player_identity_map
from src.runtime_v6.identity_scope import apply_entity_scope_identity_semantics


def _coverage_row(
    *,
    canonical: int = 3,
    mapped: int = 0,
    health: str = "RED",
    deterministic: bool = False,
    join_allowed: bool = False,
) -> dict:
    return {
        "strategy": (
            "TEST_DETERMINISTIC_BRIDGE"
            if deterministic
            else "UNRESOLVED_NO_VERIFIED_DETERMINISTIC_BRIDGE"
        ),
        "deterministic_bridge": deterministic,
        "identity_health": health,
        "mapped_status": "EXACT" if mapped else "UNMAPPED",
        "mapped_player_count": mapped,
        "canonical_player_count": canonical,
        "coverage_ratio": round(mapped / canonical, 6) if canonical else 0.0,
        "unmapped_player_count": max(0, canonical - mapped),
        "join_allowed": join_allowed,
    }


def _identity_map() -> dict:
    statsbomb = _coverage_row()
    rotowire = _coverage_row()
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
        "governance": {"fuzzy_name_matching_allowed": False},
    }


def _result(source_id: str) -> dict:
    return {
        "source_id": source_id,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "health": "GREEN",
        "availability": "AVAILABLE",
        "coverage": {"expected_requests": 1, "usable_requests": 1},
        "polling": {"skipped": False},
        "attempts": [],
        "data": {},
    }


def _source(source_id: str, scopes: list[str]) -> dict:
    return {
        "id": source_id,
        "name": source_id,
        "category": "advanced_performance",
        "critical": False,
        "entity_scopes": scopes,
        "check_freshness_minutes": 90,
    }


def _official(player_count: int) -> dict:
    return {
        "official": {
            "bootstrap": {
                "elements": [
                    {
                        "id": index,
                        "code": 1000 + index,
                        "web_name": f"P{index}",
                        "team": 1,
                        "element_type": 3,
                    }
                    for index in range(1, player_count + 1)
                ],
                "teams": [{"id": 1, "name": "One", "short_name": "ONE"}],
            },
            "fixtures": [],
        }
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


def test_entity_scopes_are_the_only_applicability_authority() -> None:
    scopes = {"provider": ["TEAM"]}
    player = resolve_entity_scope_applicability("provider", "PLAYER", scopes)
    team = resolve_entity_scope_applicability("provider", "TEAM", scopes)

    assert player["applicable"] is False
    assert player["state"] == "NOT_APPLICABLE"
    assert team["applicable"] is True
    assert team["state"] == "TEAM"


def test_source_health_consumes_canonical_source_entity_identity() -> None:
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
    config = {"sources": [_source("provider", ["PLAYER"])]}
    health = build_source_health(config, {"provider": _result("provider")}, identity)
    row = health["sources"][0]

    assert row["dimensions"]["identity_health"] == "AMBER"
    assert row["dimensions"]["identity_join_health"] == "AMBER"
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


def test_cross_representation_player_identity_and_aggregate_counts_are_consistent() -> None:
    base = {
        "canonical_authority": "official_fpl",
        "canonical_player_count": 3,
        "coverage": {
            "full": _coverage_row(
                mapped=3,
                health="GREEN",
                deterministic=True,
                join_allowed=True,
            ),
            "partial": _coverage_row(
                mapped=2,
                health="AMBER",
                deterministic=True,
                join_allowed=True,
            ),
            "unresolved": _coverage_row(),
            "not_player": _coverage_row(),
        },
        "entity_bridges": {
            "player": {
                "canonical_player_count": 3,
                "coverage": {
                    "full": _coverage_row(
                        mapped=3,
                        health="GREEN",
                        deterministic=True,
                        join_allowed=True,
                    ),
                    "partial": _coverage_row(
                        mapped=2,
                        health="AMBER",
                        deterministic=True,
                        join_allowed=True,
                    ),
                    "unresolved": _coverage_row(),
                    "not_player": _coverage_row(),
                },
            },
            "team": {"canonical_team_count": 1, "coverage": {}},
            "fixture": {"canonical_fixture_count": 1, "coverage": {}},
        },
        "governance": {"fuzzy_name_matching_allowed": False},
    }
    scopes = {
        "official_fpl": ["PLAYER"],
        "full": ["PLAYER"],
        "partial": ["PLAYER"],
        "unresolved": ["PLAYER"],
        "not_player": ["FEED"],
    }
    identity = apply_entity_scope_identity_semantics(base, scopes)
    source_ids = list(scopes)
    config = {"sources": [_source(source_id, scope) for source_id, scope in scopes.items()]}
    health = build_source_health(
        config,
        {source_id: _result(source_id) for source_id in source_ids},
        identity,
    )

    for source_id in source_ids:
        player_state = identity["coverage"][source_id]["identity_health"]
        assert identity["entity_bridges"]["player"]["coverage"][source_id]["identity_health"] == player_state
        assert identity["source_entity_identity"][source_id]["player"]["identity_health"] == player_state
        health_row = next(row for row in health["sources"] if row["source_id"] == source_id)
        assert health_row["dimensions"]["identity_health"] == player_state

    expected = Counter(identity["coverage"][source_id]["identity_health"] for source_id in source_ids)
    counts = health["dimension_counts"]["identity_health"]
    assert counts == {
        "GREEN": expected["GREEN"],
        "AMBER": expected["AMBER"],
        "RED": expected["RED"],
        "NOT_APPLICABLE": expected["NOT_APPLICABLE"],
    }
    assert sum(counts.values()) == len(source_ids)
    assert identity["coverage"]["partial"]["identity_health"] == "AMBER"
    assert identity["coverage"]["full"]["identity_health"] == "GREEN"
    assert identity["coverage"]["unresolved"]["identity_health"] == "RED"
    assert identity["coverage"]["unresolved"]["join_allowed"] is False
    assert identity["coverage"]["not_player"]["identity_health"] == "NOT_APPLICABLE"


def test_runtime_health_and_identity_join_health_are_separate_dimensions() -> None:
    base = {
        "canonical_authority": "official_fpl",
        "canonical_player_count": 3,
        "coverage": {
            "provider": _coverage_row(
                mapped=3,
                health="GREEN",
                deterministic=True,
                join_allowed=True,
            ),
        },
        "entity_bridges": {
            "player": {
                "canonical_player_count": 3,
                "coverage": {
                    "provider": _coverage_row(
                        mapped=3,
                        health="GREEN",
                        deterministic=True,
                        join_allowed=True,
                    ),
                },
            },
            "team": {
                "canonical_team_count": 1,
                "coverage": {
                    "provider": {
                        "identity_health": "RED",
                        "deterministic_bridge": False,
                        "join_allowed": False,
                        "strategy": "UNRESOLVED_NO_VERIFIED_DETERMINISTIC_BRIDGE",
                    }
                },
            },
            "fixture": {"canonical_fixture_count": 0, "coverage": {}},
        },
    }
    identity = apply_entity_scope_identity_semantics(
        base,
        {"provider": ["PLAYER", "TEAM"]},
    )
    health = build_source_health(
        {"sources": [_source("provider", ["PLAYER", "TEAM"])]},
        {"provider": _result("provider")},
        identity,
    )
    row = health["sources"][0]

    assert row["dimensions"]["transport_health"] == "GREEN"
    assert row["source_runtime_health"] == "GREEN"
    assert row["dimensions"]["identity_health"] == "GREEN"
    assert row["dimensions"]["identity_join_health"] == "RED"
    assert row["identity_join_health"] == "RED"
    assert row["overall_operational_health"] == "GREEN"
    assert row["health"] == "GREEN"
    assert row["join_ready"] is False


def test_player_not_applicable_can_coexist_with_applicable_join_red() -> None:
    base = {
        "canonical_authority": "official_fpl",
        "canonical_player_count": 3,
        "coverage": {"provider": _coverage_row()},
        "entity_bridges": {
            "player": {"canonical_player_count": 3, "coverage": {"provider": _coverage_row()}},
            "team": {
                "canonical_team_count": 1,
                "coverage": {
                    "provider": {
                        "identity_health": "RED",
                        "deterministic_bridge": False,
                        "join_allowed": False,
                    }
                },
            },
            "fixture": {"canonical_fixture_count": 0, "coverage": {}},
        },
    }
    identity = apply_entity_scope_identity_semantics(base, {"provider": ["TEAM"]})
    health = build_source_health(
        {"sources": [_source("provider", ["TEAM"])]},
        {"provider": _result("provider")},
        identity,
    )
    row = health["sources"][0]

    assert identity["coverage"]["provider"]["identity_health"] == "NOT_APPLICABLE"
    assert identity["entity_bridges"]["player"]["coverage"]["provider"]["identity_health"] == "NOT_APPLICABLE"
    assert row["dimensions"]["identity_health"] == "NOT_APPLICABLE"
    assert row["dimensions"]["identity_join_health"] == "RED"
    assert row["dimensions"]["transport_health"] == "GREEN"


def test_conflict_remains_red_and_fail_closed_without_fuzzy_repair() -> None:
    conflict = _coverage_row(
        mapped=1,
        health="RED",
        deterministic=False,
        join_allowed=False,
    )
    conflict["identity_conflict_count"] = 1
    base = {
        "canonical_authority": "official_fpl",
        "canonical_player_count": 3,
        "coverage": {"provider": conflict},
        "entity_bridges": {
            "player": {"canonical_player_count": 3, "coverage": {"provider": dict(conflict)}},
            "team": {"canonical_team_count": 0, "coverage": {}},
            "fixture": {"canonical_fixture_count": 0, "coverage": {}},
        },
        "governance": {"fuzzy_name_matching_allowed": False},
    }
    identity = apply_entity_scope_identity_semantics(base, {"provider": ["PLAYER"]})
    row = identity["coverage"]["provider"]

    assert row["identity_health"] == "RED"
    assert row["join_allowed"] is False
    assert row["identity_conflict_count"] == 1
    assert identity["governance"]["fuzzy_name_matching_allowed"] is False


def test_canonical_player_universe_tracks_current_official_bootstrap_dynamically() -> None:
    first_count = 2
    second_count = 5

    first = build_player_identity_map(
        _official(first_count),
        {"official_price_predictor": {"data": {"players": [{"id": 1}, {"id": 2}]}}},
        ["official_fpl", "official_price_predictor"],
    )
    second = build_player_identity_map(
        _official(second_count),
        {
            "official_price_predictor": {
                "data": {"players": [{"id": index} for index in range(1, second_count + 1)]}
            }
        },
        ["official_fpl", "official_price_predictor"],
    )

    assert first["canonical_player_count"] == first_count
    assert first["coverage"]["official_price_predictor"]["canonical_player_count"] == first_count
    assert second["canonical_player_count"] == second_count
    assert second["coverage"]["official_price_predictor"]["canonical_player_count"] == second_count
    assert second["coverage"]["official_price_predictor"]["mapped_player_count"] == second_count
    assert second["coverage"]["official_price_predictor"]["coverage_ratio"] == 1.0


def test_identity_runtime_and_roadmap_do_not_pin_historical_player_universe_sizes() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "src/runtime_v6/domains/identity/identity.py",
        root / "src/runtime_v6/domains/identity/identity_scope.py",
        root / "src/runtime_v6/domains/identity/identity_coverage.py",
        root / "docs/V6_IDENTITY_BRIDGE_ROADMAP.md",
    ]
    forbidden = {str(650 + 7), str(650 + 9)}

    for path in paths:
        text = path.read_text(encoding="utf-8")
        for value in forbidden:
            assert value not in text, f"{path}: pinned canonical player universe {value}"


def test_applicable_missing_row_defaults_to_red_join_disallowed() -> None:
    base = {
        "canonical_authority": "official_fpl",
        "canonical_player_count": 3,
        "coverage": {},
        "entity_bridges": {
            "player": {"canonical_player_count": 3, "coverage": {}},
            "team": {"canonical_team_count": 0, "coverage": {}},
            "fixture": {"canonical_fixture_count": 0, "coverage": {}},
        },
    }
    identity = apply_entity_scope_identity_semantics(base, {"provider": ["PLAYER"]})
    row = identity["coverage"]["provider"]

    assert row["applicable"] is True
    assert row["identity_health"] == "RED"
    assert row["deterministic_bridge"] is False
    assert row["join_allowed"] is False
    assert row["strategy"] == "UNRESOLVED_NO_VERIFIED_DETERMINISTIC_BRIDGE"
