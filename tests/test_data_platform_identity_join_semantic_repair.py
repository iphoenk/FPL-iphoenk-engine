from __future__ import annotations

from datetime import datetime, timezone

from src.runtime_v6.health import build_source_health
from src.runtime_v6.identity_coverage import build_player_identity_coverage_truth
from src.runtime_v6.identity_scope import (
    apply_entity_scope_identity_semantics,
    apply_observed_player_identity_truth,
)
from src.runtime_v6.source_native import build_source_native_datasets
from src.runtime_v6.verified_bridges import enrich_shared_identity_bridges


def _coverage(*, mapped: int, canonical: int, health: str, join_allowed: bool) -> dict:
    return {
        "strategy": "TEST_DETERMINISTIC" if mapped else "UNRESOLVED_NO_VERIFIED_DETERMINISTIC_BRIDGE",
        "deterministic_bridge": bool(mapped),
        "identity_health": health,
        "mapped_status": "EXACT" if mapped else "UNMAPPED",
        "mapped_player_count": mapped,
        "canonical_player_count": canonical,
        "coverage_ratio": mapped / canonical if canonical else 0.0,
        "unmapped_player_count": canonical - mapped,
        "join_allowed": join_allowed,
    }


def _result(source_id: str, *, failed_transport: bool = False) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "source_id": source_id,
        "checked_at": now,
        "health": "RED" if failed_transport else "GREEN",
        "availability": "UNAVAILABLE" if failed_transport else "AVAILABLE",
        "coverage": {"expected_requests": 1, "usable_requests": 0 if failed_transport else 1},
        "polling": {"skipped": False},
        "attempts": (
            [{"status": "UNAVAILABLE", "checked_at": now}]
            if failed_transport
            else []
        ),
        "data": {},
    }


def _source(source_id: str, scopes: list[str], *, critical: bool = False) -> dict:
    return {
        "id": source_id,
        "name": source_id,
        "category": "identity-test",
        "critical": critical,
        "entity_scopes": scopes,
        "check_freshness_minutes": 90,
    }


def test_observed_actionable_gap_overrides_partial_canonical_amber_to_red() -> None:
    partial = _coverage(mapped=2, canonical=3, health="AMBER", join_allowed=True)
    base = {
        "canonical_authority": "official_fpl",
        "canonical_player_count": 3,
        "coverage": {"provider": dict(partial)},
        "entity_bridges": {
            "player": {"canonical_player_count": 3, "coverage": {"provider": dict(partial)}},
            "team": {"canonical_team_count": 0, "coverage": {}},
            "fixture": {"canonical_fixture_count": 0, "coverage": {}},
        },
    }
    scoped = apply_entity_scope_identity_semantics(base, {"provider": ["PLAYER"]})
    truth = {
        "sources": {
            "provider": {
                "player_identity_health": "RED",
                "canonical_coverage_ratio": 2 / 3,
                "observed_provider_player_count": 2,
                "observed_join_eligible_player_count": 2,
                "observed_joined_player_count": 1,
                "observed_unmapped_player_count": 1,
                "observed_reviewed_provider_limitation_count": 0,
                "observed_join_coverage_ratio": 0.5,
                "provider_max_observed_join_coverage_ratio": 0.5,
                "provider_universe_completeness": "PARTIAL_QUERY_RESULT",
                "absence_classification_status": "NOT_PROVEN",
                "provider_native_classification_counts": {
                    "VERIFIED": 1,
                    "ACTIONABLE_UNMAPPED": 1,
                    "REVIEWED_PROVIDER_LIMITATION": 0,
                    "NO_PROVIDER_ENTITY": 0,
                    "NOT_APPLICABLE": 0,
                    "CONFLICT": 0,
                },
                "identity_health_reason": "ACTIONABLE_UNMAPPED_OR_IDENTITY_CONFLICT",
            }
        }
    }
    repaired = apply_observed_player_identity_truth(scoped, truth)
    row = repaired["source_entity_identity"]["provider"]["player"]
    assert row["identity_health"] == "RED"
    assert row["observed_actionable_unmapped_count"] == 1
    assert row["join_allowed"] is True
    assert row["join_permission_scope"] == "VERIFIED_ROWS_ONLY"
    assert repaired["source_entity_identity"]["provider"]["identity_health"] == "RED"


def test_canonical_and_observed_player_coverage_are_separate_metrics() -> None:
    identity = {
        "canonical_player_count": 2,
        "mappings": {
            "1": {
                "official_fpl_element_id": 1,
                "links": {
                    "statmuse": {"source_native_id": 101, "status": "VERIFIED_MANUAL"}
                },
            },
            "2": {"official_fpl_element_id": 2, "links": {}},
        },
        "coverage": {
            "statmuse": {
                "mapped_player_count": 1,
                "mapped_status": "VERIFIED_MANUAL",
                "join_allowed": True,
                "configured_mapping_count": 1,
                "duplicate_canonical_code_count": 0,
                "conflicting_existing_link_count": 0,
            }
        },
    }
    datasets = {
        "statmuse": {
            "record_groups": {
                "players": [
                    {
                        "source_native_id": 101,
                        "official_element_id": 1,
                        "identity_status": "VERIFIED_MANUAL",
                    }
                ]
            }
        }
    }
    evidence = {
        "schema_version": 1,
        "canonical_authority": "official_fpl",
        "fuzzy_name_matching_allowed": False,
        "reviewed_provider_limitations": {
            "policy": "EXPLICIT_NATIVE_ID_ALLOWLIST_ONLY",
            "classification": "REVIEWED_PROVIDER_LIMITATION",
            "sources": {},
        },
        "governance": {},
    }
    row = build_player_identity_coverage_truth(identity, datasets, evidence)["sources"]["statmuse"]
    assert row["canonical_coverage_ratio"] == 0.5
    assert row["observed_join_coverage_ratio"] == 1.0
    assert row["provider_max_observed_join_coverage_ratio"] == 1.0
    assert row["absence_classification_status"] == "NOT_PROVEN"
    assert row["no_provider_entity_count"] is None
    assert row["player_identity_health"] == "AMBER"
    assert row["canonical_classification_counts"]["UNKNOWN_PROVIDER_PRESENCE"] == 1
    assert row["provider_native_classification_counts"]["NOT_APPLICABLE"] == 0


def test_secondary_identity_red_does_not_rewrite_official_canonical_green() -> None:
    unresolved = _coverage(mapped=0, canonical=2, health="RED", join_allowed=False)
    base = {
        "canonical_authority": "official_fpl",
        "canonical_player_count": 2,
        "coverage": {"provider": dict(unresolved)},
        "entity_bridges": {
            "player": {"canonical_player_count": 2, "coverage": {"provider": dict(unresolved)}},
            "team": {"canonical_team_count": 1, "coverage": {"provider": {
                "identity_health": "RED",
                "deterministic_bridge": False,
                "join_allowed": False,
            }}},
            "fixture": {"canonical_fixture_count": 1, "coverage": {}},
        },
    }
    scopes = {
        "official_fpl": ["PLAYER", "TEAM", "FIXTURE"],
        "provider": ["PLAYER", "TEAM"],
    }
    identity = apply_entity_scope_identity_semantics(base, scopes)
    config = {
        "sources": [
            _source("official_fpl", ["PLAYER", "TEAM", "FIXTURE"], critical=True),
            _source("provider", ["PLAYER", "TEAM"], critical=False),
        ]
    }
    health = build_source_health(
        config,
        {
            "official_fpl": _result("official_fpl"),
            "provider": _result("provider"),
        },
        identity,
    )
    assert health["canonical_identity_health"] == "GREEN"
    assert health["canonical_identity_corruption"] is False
    assert health["identity_join_health_overall"] == "RED"
    assert health["identity_join_health_overall_classification"] == (
        "RED_TRUTHFUL_NONBLOCKING_SECONDARY_PROVIDER_GAPS"
    )
    assert health["critical_identity_red_sources"] == []
    provider = next(row for row in health["sources"] if row["source_id"] == "provider")
    assert provider["source_runtime_health"] == "GREEN"
    assert provider["identity_join_health"] == "RED"


def test_genuine_nonapplicable_scope_is_not_counted_as_identity_failure() -> None:
    identity = apply_entity_scope_identity_semantics(
        {
            "canonical_authority": "official_fpl",
            "canonical_player_count": 1,
            "coverage": {"statsbomb": _coverage(mapped=0, canonical=1, health="RED", join_allowed=False)},
            "entity_bridges": {
                "player": {
                    "canonical_player_count": 1,
                    "coverage": {"statsbomb": _coverage(mapped=0, canonical=1, health="RED", join_allowed=False)},
                },
                "team": {"canonical_team_count": 1, "coverage": {}},
                "fixture": {"canonical_fixture_count": 1, "coverage": {}},
            },
        },
        {"statsbomb": ["COMPETITION", "EVENT", "FEED"]},
    )
    row = identity["source_entity_identity"]["statsbomb"]
    assert row["identity_health"] == "NOT_APPLICABLE"
    assert row["player"]["identity_health"] == "NOT_APPLICABLE"
    assert row["team"]["identity_health"] == "NOT_APPLICABLE"
    assert row["fixture"]["identity_health"] == "NOT_APPLICABLE"


def test_vaastav_shared_fixture_id_survives_kickoff_reschedule_without_name_join() -> None:
    identity = {
        "entity_bridges": {
            "team": {
                "canonical_team_count": 2,
                "mappings": {
                    "1": {"official_fpl_team_id": 1, "links": {}},
                    "2": {"official_fpl_team_id": 2, "links": {}},
                },
                "coverage": {},
            },
            "fixture": {
                "canonical_fixture_count": 1,
                "mappings": {
                    "10": {
                        "official_fpl_fixture_id": 10,
                        "official_fpl_team_h_id": 1,
                        "official_fpl_team_a_id": 2,
                        "event": 1,
                        "kickoff_time": "2026-09-20T13:00:00Z",
                        "links": {},
                    }
                },
                "coverage": {},
            },
        },
        "governance": {"fuzzy_name_matching_allowed": False},
    }
    official = {
        "official": {
            "bootstrap": {
                "elements": [
                    {"id": 1, "code": 101, "team": 1},
                    {"id": 2, "code": 202, "team": 2},
                ],
                "teams": [{"id": 1}, {"id": 2}],
            },
            "fixtures": [
                {
                    "id": 10,
                    "event": 1,
                    "team_h": 1,
                    "team_a": 2,
                    "kickoff_time": "2026-09-20T13:00:00Z",
                }
            ],
        }
    }
    vaastav = {
        "source_id": "vaastav_fpl",
        "health": "AMBER",
        "checked_at": "2026-09-19T09:00:00Z",
        "data": {
            "players_raw": {
                "body": (
                    "id,code,team\n"
                    "1,101,1\n"
                    "2,202,2\n"
                )
            },
            "fixtures": {
                "body": (
                    "id,event,kickoff_time,team_h,team_a,finished\n"
                    "10,1,2026-09-19T14:00:00Z,1,2,false\n"
                )
            },
        },
    }
    repaired = enrich_shared_identity_bridges(
        identity, official, {"vaastav_fpl": vaastav}
    )
    coverage = repaired["entity_bridges"]["fixture"]["coverage"]["vaastav_fpl"]
    assert coverage["identity_health"] == "GREEN"
    assert coverage["mapped_fixture_count"] == 1
    assert coverage["kickoff_mismatch_count"] == 1
    assert coverage["kickoff_time_is_mutable_not_identity_key"] is True
    link = repaired["entity_bridges"]["fixture"]["mappings"]["10"]["links"]["vaastav_fpl"]
    assert link["status"] == "EXACT"
    assert link["provenance"]["kickoff_matches_current_official"] is False
    assert link["provenance"]["kickoff_time_is_mutable_not_identity_key"] is True

    dataset = build_source_native_datasets(
        {"vaastav_fpl": vaastav}, repaired
    )["vaastav_fpl"]
    fixture = dataset["record_groups"]["fixtures"][0]
    assert fixture["official_fixture_id"] == 10
    assert fixture["identity_status"] == "EXACT"


def test_vaastav_transport_degradation_stays_separate_from_identity_health() -> None:
    base = {
        "canonical_authority": "official_fpl",
        "canonical_player_count": 1,
        "coverage": {
            "vaastav_fpl": _coverage(mapped=1, canonical=1, health="GREEN", join_allowed=True)
        },
        "entity_bridges": {
            "player": {
                "canonical_player_count": 1,
                "coverage": {
                    "vaastav_fpl": _coverage(mapped=1, canonical=1, health="GREEN", join_allowed=True)
                },
            },
            "team": {
                "canonical_team_count": 1,
                "coverage": {
                    "vaastav_fpl": {
                        "identity_health": "GREEN",
                        "deterministic_bridge": True,
                        "join_allowed": True,
                    }
                },
            },
            "fixture": {
                "canonical_fixture_count": 1,
                "coverage": {
                    "vaastav_fpl": {
                        "identity_health": "GREEN",
                        "deterministic_bridge": True,
                        "join_allowed": True,
                    }
                },
            },
        },
    }
    identity = apply_entity_scope_identity_semantics(
        base, {"vaastav_fpl": ["PLAYER", "TEAM", "FIXTURE"]}
    )
    health = build_source_health(
        {"sources": [_source("vaastav_fpl", ["PLAYER", "TEAM", "FIXTURE"])]},
        {"vaastav_fpl": _result("vaastav_fpl", failed_transport=True)},
        identity,
    )
    row = health["sources"][0]
    assert row["source_runtime_health"] == "RED"
    assert row["identity_join_health"] == "GREEN"
    assert row["dimensions"]["identity_health"] == "GREEN"


def test_identity_repair_code_has_no_fuzzy_or_name_join_strategy() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "src/runtime_v6/domains/identity/verified_bridges.py",
        root / "src/runtime_v6/domains/identity/verified_crosswalks.py",
        root / "src/runtime_v6/domains/identity/identity_coverage.py",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "fuzzy_matching_used" in text or "fuzzy_matching_allowed" in text
    assert "name_matching_used" in text or "name_matching_allowed" in text
    assert "difflib" not in text
    assert "SequenceMatcher" not in text
    assert "rapidfuzz" not in text
